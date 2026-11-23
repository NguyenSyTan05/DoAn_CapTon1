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

import logging
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger("classbridge.rooms")

HISTORY_LIMIT = 50
MAX_ROOMS = 200


@dataclass
class _Subscriber:
    websocket: WebSocket
    progressive: bool


@dataclass
class Room:
    session: str
    subscribers: list[_Subscriber] = field(default_factory=list)
    history: deque = field(default_factory=lambda: deque(maxlen=HISTORY_LIMIT))
    seq: int = 0

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
            await subscriber.websocket.send_json(message)
        except Exception:  # kết nối đã chết -> bỏ khỏi phòng
            self.leave(room.session, subscriber.websocket)

    async def publish_final(self, session: str, message: dict[str, Any]) -> None:
        """Lời gốc vừa nhận dạng xong: chỉ người xem 'progressive' nhận ngay."""
        room = self.room(session)
        for sub in list(room.subscribers):
            if sub.progressive:
                await self._send(room, sub, message)

    async def publish_translation(
        self, session: str, translation_msg: dict[str, Any], combined_msg: dict[str, Any]
    ) -> None:
        """Bản dịch xong: progressive nhận tin dịch, legacy nhận tin gộp một lần."""
        room = self.room(session)
        room.history.append(combined_msg)
        for sub in list(room.subscribers):
            await self._send(room, sub, translation_msg if sub.progressive else combined_msg)
