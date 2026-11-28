"""
router.py (modules/live_translate)
====================================
Live Audio Translation (WebSocket) THEO PHIÊN HỌC.

  /api/v1/ws/live-translate?session=<id>&role=lecturer|viewer&lang=auto|vi|en
                           &fmt=webm|pcm16|pcm32&progressive=0|1

- role=lecturer: gửi âm thanh. Luồng PCM được cắt thành câu nói theo khoảng lặng
  (segmenter.py), nhận dạng bằng SpeechEngine, dịch bằng NLLB-200, rồi phát cho MỌI người
  trong phòng `session` (rooms.py).
- role=viewer (mặc định khi có `session`): chỉ nhận phụ đề, mọi dữ liệu gửi lên bị bỏ qua.
- Không có `session`: phòng mặc định dùng chung, và kết nối được coi là giảng viên
  (tương thích /room và /student cũ).
- fmt=webm (mặc định): gói WebM/Opus từ MediaRecorder như bản cũ; pcm16/pcm32: PCM 16 kHz thô
  (AudioWorklet) — độ trễ thấp hơn, nên dùng cho giảng viên.
- progressive=1: nhận "final" (lời gốc) ngay, "translation" sau; mặc định gửi MỘT tin gộp
  {original_text, translated_text, source_lang, ...} như bản cũ.

Điều khiển từ giảng viên (khung text JSON): {"action":"set_language","language":"vi|en|auto"},
{"action":"end"}, {"action":"ping"}.

Chưa xác thực: ai biết session_id đều vào được (xem README).
"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import os
import re
import time
import wave
from pathlib import Path
from typing import Any

import numpy
from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect

from core import auth as auth_core
from core.ai import ai_service
from core.auth import ANY_MEMBER, require_room_access, verify_ws_access
from core.session_scope import normalize_session, session_param
from modules.live_translate.audio_utils import (
    TARGET_SAMPLE_RATE,
    decode_pcm16,
    decode_pcm32,
    preprocess_audio_for_stt,
    xuly_am_thanh,
)
from modules.live_translate.rooms import RoomRegistry
from modules.live_translate.segmenter import UtteranceSegmenter
from modules.live_translate.speech_engine import SpeechEngine
from modules.live_translate.text_filters import (
    apply_vi_tone_correction,
    decide_language,
    finalize_text,
    is_decoder_loop,
    is_hallucination,
    remove_repeated_phrases,
)

logger = logging.getLogger("classbridge.live_translate")

router = APIRouter()

MAX_FRAME_BYTES = 8 * 1024 * 1024
MAX_QUEUE = 8  # đủ chứa các mệnh đề liên tiếp của giảng viên mà không rớt câu
LANGS = {"auto", "vi", "en"}
# Ghi âm giọng giảng viên để đối chiếu/đo WER: MẶC ĐỊNH TẮT (quyền riêng tư + dung lượng đĩa).
# Bật bằng STT_SAVE_AUDIO=1. Ghi nối đuôi PCM16 (chi phí O(1)).
_seg_counter = itertools.count(1)
_RECORDINGS_DIR = Path(__file__).resolve().parents[2] / "transcripts" / "recordings"


def _save_audio_enabled() -> bool:
    return os.getenv("STT_SAVE_AUDIO") == "1"


def _safe_session_name(session: str | None) -> str:
    return re.sub(r"[^a-zA-Z0-9_\-]", "_", session or "default")[:80] or "default"


def _save_utterance_wav(session: str, audio: numpy.ndarray) -> str | None:
    """Lưu WAV 16 kHz mono của một câu nói (tên duy nhất) và nối PCM16 thô vào file cả buổi."""
    try:
        safe = _safe_session_name(session)
        sess_dir = _RECORDINGS_DIR / safe
        sess_dir.mkdir(parents=True, exist_ok=True)
        seg_path = sess_dir / f"seg_{int(time.time())}_{next(_seg_counter):06d}.wav"

        norm_audio = preprocess_audio_for_stt(audio)
        pcm16 = numpy.clip(norm_audio * 32767.0, -32768, 32767).astype(numpy.int16).tobytes()

        with wave.open(str(seg_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(TARGET_SAMPLE_RATE)
            wf.writeframes(pcm16)

        with open(_RECORDINGS_DIR / f"{safe}_full_lecture.pcm16", "ab") as full:
            full.write(pcm16)

        return str(seg_path)
    except Exception:
        logger.debug("Không lưu được WAV cho phiên '%s'", session, exc_info=True)
        return None


def decode_frame(data: bytes, fmt: str) -> numpy.ndarray:
    """Giải mã một gói nhị phân thành PCM float32 16 kHz mono."""
    if not data or len(data) > MAX_FRAME_BYTES:
        return numpy.empty(0, dtype=numpy.float32)
    if fmt == "pcm16":
        return decode_pcm16(data)
    if fmt == "pcm32":
        return decode_pcm32(data)
    return xuly_am_thanh(data)  # webm/opus (bản cũ)


async def _process_utterance(
    app_state: Any,
    scope: str,
    audio: numpy.ndarray,
    language: str,
    translations: set[asyncio.Task],
    order_lock: asyncio.Lock,
) -> None:
    engine: SpeechEngine = app_state.speech_engine
    rooms: RoomRegistry = app_state.live_rooms
    started = time.perf_counter()

    # Chỉ lưu file WAV khi bật STT_SAVE_AUDIO=1 (tránh tốn đĩa & đảm bảo riêng tư)
    wav_path = (
        await asyncio.to_thread(_save_utterance_wav, scope, audio)
        if _save_audio_enabled()
        else None
    )

    forced_lang = None if language == "auto" else language
    result = await asyncio.to_thread(engine.transcribe, audio, forced_lang)
    if result is None:
        return
    raw_text = result.text
    if is_decoder_loop(raw_text):
        return
    text = finalize_text(raw_text)
    if not text or is_hallucination(
        text,
        no_speech_prob=result.no_speech_prob,
        avg_logprob=result.avg_logprob,
        forced_lang=forced_lang,
        detected_lang=result.language,
    ):
        return

    # Sửa lỗi dấu thanh điệu tiếng Việt (underthesea nếu đã cài, không ảnh hưởng tiếng Anh)
    det_lang_hint = forced_lang or result.language
    if det_lang_hint == "vi" or (det_lang_hint is None and result.language_prob < 0.7):
        text = apply_vi_tone_correction(text)

    source = decide_language(text, result.language, result.language_prob)
    target = "vi" if source == "en" else "en"
    segment_id = rooms.room(scope).next_segment_id()
    stamp = time.strftime("%H:%M:%S")
    stt_seconds = round(time.perf_counter() - started, 3)
    logger.info("🎙️ STT [%s] %.2fs: %s", source, stt_seconds, text)

    # 1) Lời gốc hiện ngay cho người xem 'progressive'
    await rooms.publish_final(
        scope,
        {
            "type": "final", "segment_id": segment_id, "original_text": text,
            "source_lang": source, "target_lang": target, "timestamp": stamp,
        },
    )

    # 2) Dịch chạy nền để không chặn câu kế tiếp; khóa FIFO giữ đúng thứ tự câu khi ghi history/gửi
    async def translate() -> None:
        async with order_lock:
            try:
                translated = await asyncio.to_thread(ai_service.transcript_text, text, source, target)
            except Exception:
                logger.exception("Dịch thất bại")
                translated = ""
            translated = remove_repeated_phrases(translated)
            await rooms.publish_translation(
                scope,
                {"type": "translation", "segment_id": segment_id,
                 "translated_text": translated, "target_lang": target},
                {"type": "result", "segment_id": segment_id, "original_text": text,
                 "translated_text": translated, "source_lang": source, "target_lang": target,
                 "stt_sec": stt_seconds, "duration_sec": round(time.perf_counter() - started, 3),
                 "audio_file": wav_path, "timestamp": stamp},
            )

    task = asyncio.create_task(translate())
    translations.add(task)
    task.add_done_callback(translations.discard)


@router.get(
    "/api/v1/transcripts",
    dependencies=[Depends(require_room_access(ANY_MEMBER, allow_closed=True))],
)
async def get_session_transcripts(
    session: str = Depends(session_param),
) -> dict[str, Any]:
    """Lấy toàn bộ bản ghi lời giảng & bản dịch đã lưu của phiên học."""
    from pathlib import Path
    import re

    safe_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", session or "default")[:80] or "default"
    jsonl_path = Path(__file__).resolve().parents[2] / "transcripts" / f"{safe_name}.jsonl"
    items: list[dict[str, Any]] = []
    if jsonl_path.is_file():
        with open(jsonl_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        items.append(json.loads(line))
                    except ValueError:
                        continue
    return {"session": session, "count": len(items), "items": items}


@router.websocket("/api/v1/ws/live-translate")
async def live_translate(
    websocket: WebSocket,
    session: str | None = Query(None),
    role: str | None = Query(None),
    lang: str = Query("auto"),
    fmt: str = Query("webm"),
    progressive: bool = Query(False),
) -> None:
    scope = normalize_session(session)
    if scope is None or fmt not in {"webm", "pcm16", "pcm32"}:
        await websocket.close(code=1008)  # tham số sai định dạng
        return

    ws_access = await verify_ws_access(websocket, scope, ANY_MEMBER)
    if ws_access is None:
        await websocket.close(code=1008)  # thiếu hoặc sai quyền truy cập phòng
        return

    requested_lecturer = role == "lecturer" or (role is None and not session)
    is_lecturer = (
        requested_lecturer and ws_access.access == "lecturer"
        if auth_core.settings.enabled
        else requested_lecturer
    )
    language = lang if lang in LANGS else "auto"
    rooms: RoomRegistry = websocket.app.state.live_rooms
    app_state = websocket.app.state

    await websocket.accept()
    room = rooms.join(scope, websocket, progressive)
    logger.info("🟢 WS %s vào phòng '%s' (%s)", "giảng viên" if is_lecturer else "người xem", scope or "mặc định", websocket.client)
    if progressive and room.history:
        await websocket.send_json({"type": "history", "items": list(room.history)})

    segmenter = UtteranceSegmenter()
    queue: asyncio.Queue[tuple[numpy.ndarray, str] | None] = asyncio.Queue(maxsize=MAX_QUEUE)
    translations: set[asyncio.Task] = set()
    order_lock = room.order_lock

    async def worker() -> None:
        while True:
            item = await queue.get()
            if item is None:
                return
            audio, utt_lang = item
            try:
                await _process_utterance(app_state, scope, audio, utt_lang, translations, order_lock)
            except Exception:
                logger.exception("Lỗi xử lý câu nói, duy trì kết nối")

    def enqueue(audio: numpy.ndarray, utt_lang: str) -> None:
        if queue.full():
            try:
                queue.get_nowait()  # bỏ câu cũ nhất khi quá tải
                logger.warning("Hàng đợi STT đầy (%d), bỏ 1 đoạn cũ để giữ thời gian thực", MAX_QUEUE)
            except asyncio.QueueEmpty:
                pass
        queue.put_nowait((audio, utt_lang))

    worker_task = asyncio.create_task(worker()) if is_lecturer else None

    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break

            if message.get("text") is not None:
                try:
                    data = json.loads(message["text"])
                except ValueError:
                    continue
                action = data.get("action") or data.get("type")
                if action == "ping":
                    await websocket.send_json({"type": "pong"})
                elif action == "set_language" and is_lecturer:
                    new_lang = str(data.get("language", "auto")).lower()
                    language = new_lang if new_lang in LANGS else "auto"
                    await websocket.send_json({"type": "language_changed", "language": language})
                elif action == "clear_history" and is_lecturer:
                    await rooms.clear_room(scope)
                elif action == "end" and is_lecturer:
                    tail = segmenter.flush()
                    if tail is not None:
                        enqueue(tail, language)
                continue

            raw = message.get("bytes")
            if raw and is_lecturer:  # người xem không được phép đẩy âm thanh
                try:
                    pcm = await asyncio.to_thread(decode_frame, raw, fmt)
                except ValueError as exc:
                    logger.warning("Đã bỏ qua gói audio lỗi: %s", exc)
                    continue
                for utterance in segmenter.feed(pcm):
                    enqueue(utterance, language)
    except WebSocketDisconnect:
        pass
    finally:
        rooms.leave(scope, websocket)
        if worker_task is not None:
            tail = segmenter.flush()
            try:
                if tail is not None:
                    await asyncio.wait_for(queue.put((tail, language)), timeout=30)
                await asyncio.wait_for(queue.put(None), timeout=30)
                await asyncio.wait_for(worker_task, timeout=60)
                if translations:
                    await asyncio.wait(translations, timeout=30)
            except (asyncio.TimeoutError, Exception):
                worker_task.cancel()
            finally:
                for pending in list(translations):
                    if not pending.done():
                        pending.cancel()
        logger.info("🔴 WS đã rời phòng '%s' (%s)", scope or "mặc định", websocket.client)
