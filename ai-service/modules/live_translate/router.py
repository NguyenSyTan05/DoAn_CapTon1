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
import json
import logging
import time
from typing import Any

import numpy
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from core.ai import ai_service
from core.session_scope import normalize_session
from modules.live_translate.audio_utils import decode_pcm16, decode_pcm32, xuly_am_thanh
from modules.live_translate.rooms import RoomRegistry
from modules.live_translate.segmenter import UtteranceSegmenter
from modules.live_translate.speech_engine import SpeechEngine
from modules.live_translate.text_filters import (
    decide_language,
    finalize_text,
    is_hallucination,
    remove_repeated_phrases,
)

logger = logging.getLogger("classbridge.live_translate")

router = APIRouter()

MAX_FRAME_BYTES = 8 * 1024 * 1024
MAX_QUEUE = 2  # giữ hàng đợi ngắn để không bao giờ tích tụ độ trễ hàng chục giây
LANGS = {"auto", "vi", "en"}


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
    app_state: Any, scope: str, audio: numpy.ndarray, language: str, translations: set[asyncio.Task]
) -> None:
    engine: SpeechEngine = app_state.speech_engine
    rooms: RoomRegistry = app_state.live_rooms
    started = time.perf_counter()

    forced_lang = None if language == "auto" else language
    result = await asyncio.to_thread(engine.transcribe, audio, forced_lang)
    if result is None:
        return
    text = finalize_text(result.text)
    if not text or is_hallucination(
        text,
        no_speech_prob=result.no_speech_prob,
        avg_logprob=result.avg_logprob,
        forced_lang=forced_lang,
        detected_lang=result.language,
    ):
        return

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

    # 2) Dịch chạy nền để không chặn câu kế tiếp
    async def translate() -> None:
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
             "timestamp": stamp},
        )

    task = asyncio.create_task(translate())
    translations.add(task)
    task.add_done_callback(translations.discard)


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

    is_lecturer = role == "lecturer" or (role is None and not session)
    language = lang if lang in LANGS else "auto"
    rooms: RoomRegistry = websocket.app.state.live_rooms
    app_state = websocket.app.state

    await websocket.accept()
    room = rooms.join(scope, websocket, progressive)
    logger.info("🟢 WS %s vào phòng '%s' (%s)", "giảng viên" if is_lecturer else "người xem", scope or "mặc định", websocket.client)
    if progressive and room.history:
        await websocket.send_json({"type": "history", "items": list(room.history)})

    segmenter = UtteranceSegmenter()
    queue: asyncio.Queue = asyncio.Queue(maxsize=MAX_QUEUE)
    translations: set[asyncio.Task] = set()

    async def worker() -> None:
        while True:
            audio = await queue.get()
            if audio is None:
                return
            try:
                await _process_utterance(app_state, scope, audio, language, translations)
            except Exception:
                logger.exception("Lỗi xử lý câu nói, duy trì kết nối")

    def enqueue(audio: numpy.ndarray) -> None:
        if queue.full():
            try:
                queue.get_nowait()  # bỏ câu cũ nhất
            except asyncio.QueueEmpty:
                pass
        queue.put_nowait(audio)

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
                elif action == "end" and is_lecturer:
                    tail = segmenter.flush()
                    if tail is not None:
                        enqueue(tail)
                continue

            raw = message.get("bytes")
            if raw and is_lecturer:  # người xem không được phép đẩy âm thanh
                try:
                    pcm = await asyncio.to_thread(decode_frame, raw, fmt)
                except ValueError as exc:
                    logger.warning("Đã bỏ qua gói audio lỗi: %s", exc)
                    continue
                for utterance in segmenter.feed(pcm):
                    enqueue(utterance)
    except WebSocketDisconnect:
        pass
    finally:
        rooms.leave(scope, websocket)
        if worker_task is not None:
            tail = segmenter.flush()
            if tail is not None:
                enqueue(tail)
            enqueue(None)  # type: ignore[arg-type]
            try:
                await asyncio.wait_for(worker_task, timeout=30)
                if translations:
                    await asyncio.wait(translations, timeout=30)
            except (asyncio.TimeoutError, Exception):
                worker_task.cancel()
        logger.info("🔴 WS đã rời phòng '%s' (%s)", scope or "mặc định", websocket.client)
