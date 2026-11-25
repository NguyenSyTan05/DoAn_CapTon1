"""
rooms.py (modules/live_translate)
===================================
[CUSTOM] Phòng dịch trực tiếp theo PHIÊN HỌC: giảng viên gửi âm thanh, mọi sinh viên cùng
`session` nhận phụ đề. Bản gốc (`/ws/live-translate`) là kênh riêng cho từng kết nối nên
sinh viên không nhận được gì.

Mỗi người xem có thể chọn giao thức:
- legacy (mặc định): MỘT tin nhắn khi đã dịch xong -> frontend cũ chạy không đổi.
- progressive: tin "final" (lời gốc) gửi ngay, tin "translation" gửi sau -> lời gốc hiện sớm.
Phòng giữ HISTORY_LIMIT dòng gần nhất để người vào muộn (giao thức progressive) thấy ngay.

Chưa xác thực: ai biết session_id đều vào được. Xem README ai-service.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger("classbridge.rooms")

HISTORY_LIMIT = 500
MAX_ROOMS = 200
SEND_TIMEOUT_SECONDS = 5.0
_TRANSCRIPTS_DIR = Path(__file__).resolve().parents[2] / "transcripts"


def _append_transcript_record(session: str, item: dict[str, Any]) -> None:
    """Ghi bền vững từng câu đã nhận dạng & dịch ra file UTF-8 theo phiên học."""
    try:
        _TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", session or "default")[:80] or "default"
        jsonl_path = _TRANSCRIPTS_DIR / f"{safe_name}.jsonl"
        txt_path = _TRANSCRIPTS_DIR / f"{safe_name}.txt"
        with open(jsonl_path, "a", encoding="utf-8") as jf:
            jf.write(json.dumps(item, ensure_ascii=False) + "\n")
        stamp = item.get("timestamp", "")
        src = str(item.get("source_lang", "")).upper()
        orig = item.get("original_text", "")
        trans = item.get("translated_text", "")
        with open(txt_path, "a", encoding="utf-8") as tf:
            tf.write(f"[{stamp}] ({src}) {orig}\n")
            if trans:
                tf.write(f"         -> {trans}\n")
    except Exception:
        logger.debug("Không ghi được file transcript cho phiên '%s'", session, exc_info=True)


@dataclass
class _Subscriber:
    websocket: WebSocket
    progressive: bool


@dataclass
class Room:
    session: str
    subscribers: list[_Subscriber] = field(default_factory=list)
    history: deque = field(default_factory=lambda: deque(maxlen=HISTORY_LIMIT))
    # Khởi tạo seq theo epoch-ms để khi khởi động lại backend không bao giờ trùng lại seg-1, seg-2
    # đang có sẵn trên state React của trình duyệt người dùng.
    seq: int = field(default_factory=lambda: int(time.time() * 1000) % 1_000_000_000)
    order_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def next_segment_id(self) -> int:
        self.seq += 1
        return self.seq


class RoomRegistry:
    def __init__(self, max_rooms: int = MAX_ROOMS) -> None:
        self._rooms: "OrderedDict[str, Room]" = OrderedDict()
        self._max = max_rooms

    def room(self, session: str) -> Room:
        room = self._rooms.get(session)
        if room is None:
            room = Room(session)
            self._rooms[session] = room
            while len(self._rooms) > self._max:
                victim = next((k for k, r in self._rooms.items() if not r.subscribers and k != session), None)
                if victim is None:
                    break
                del self._rooms[victim]
        else:
            self._rooms.move_to_end(session)
        return room

    def join(self, session: str, websocket: WebSocket, progressive: bool) -> Room:
        room = self.room(session)
        room.subscribers.append(_Subscriber(websocket, progressive))
        return room

    def leave(self, session: str, websocket: WebSocket) -> None:
        room = self._rooms.get(session)
        if room:
            room.subscribers = [s for s in room.subscribers if s.websocket is not websocket]

    def viewer_count(self, session: str) -> int:
        room = self._rooms.get(session)
        return len(room.subscribers) if room else 0

    # ------------------------------------------------------------------
    async def _send(self, room: Room, subscriber: _Subscriber, message: dict[str, Any]) -> None:
        try:
            await asyncio.wait_for(
                subscriber.websocket.send_json(message),
                timeout=SEND_TIMEOUT_SECONDS,
            )
        except Exception:  # kết nối đã chết hoặc quá chậm -> bỏ khỏi phòng
            self.leave(room.session, subscriber.websocket)

    async def clear_room(self, session: str) -> None:
        """Xoá lịch sử phụ đề trong RAM + file transcript của phiên và báo mọi client xoá màn hình."""
        room = self.room(session)
        room.history.clear()
        try:
            safe_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", session or "default")[:80] or "default"
            for ext in ("jsonl", "txt"):
                p = _TRANSCRIPTS_DIR / f"{safe_name}.{ext}"
                if p.is_file():
                    p.unlink()
        except Exception:
            logger.debug("Không xoá được file transcript cũ của '%s'", session, exc_info=True)
        targets = list(room.subscribers)
        if targets:
            await asyncio.gather(
                *(self._send(room, sub, {"type": "clear"}) for sub in targets),
                return_exceptions=True,
            )

    async def publish_final(self, session: str, message: dict[str, Any]) -> None:
        """Lời gốc vừa nhận dạng xong: phát song song cho mọi người xem 'progressive'."""
        room = self.room(session)
        targets = [sub for sub in list(room.subscribers) if sub.progressive]
        if targets:
            await asyncio.gather(
                *(self._send(room, sub, message) for sub in targets),
                return_exceptions=True,
            )

    async def publish_translation(
        self, session: str, translation_msg: dict[str, Any], combined_msg: dict[str, Any]
    ) -> None:
        """Bản dịch xong: phát song song để 1 client lag không chặn cả phòng."""
        room = self.room(session)
        room.history.append(combined_msg)
        await asyncio.to_thread(_append_transcript_record, session, combined_msg)
        targets = list(room.subscribers)
        if targets:
            await asyncio.gather(
                *(
                    self._send(room, sub, translation_msg if sub.progressive else combined_msg)
                    for sub in targets
                ),
                return_exceptions=True,
            )
