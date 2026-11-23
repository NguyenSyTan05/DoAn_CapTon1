"""
stt_main.py
===========
Điểm chạy độc lập (CLI / hàm xử lý âm thanh -> văn bản) cho module STT của ClassBridge.
Dùng chung toàn bộ pipeline đã tối ưu với FastAPI server:
  audio_utils (decode + chuẩn hóa PCM) -> UtteranceSegmenter -> WhisperEngine (VI/EN) -> text_filters.

Ví dụ chạy:
  python stt_main.py --audio bai_giang.wav --lang auto
  python stt_main.py --audio english_clip.mp3 --lang en --no-segment
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
except Exception:
    pass

from modules.live_translate.audio_utils import load_audio_file
from modules.live_translate.segmenter import FRAME_SAMPLES, UtteranceSegmenter
from modules.live_translate.speech_engine import WhisperEngine
from modules.live_translate.text_filters import (
    decide_language,
    finalize_text,
    is_hallucination,
)


def _transcribe_chunk(
    pcm_chunk: np.ndarray,
    engine: WhisperEngine,
    forced_lang: str | None,
) -> dict | None:
    """Gọi WhisperEngine (đã tự tiền xử lý PCM bên trong) và lọc ảo giác."""
    started = time.perf_counter()
    result = engine.transcribe(pcm_chunk, language=forced_lang)
    if result is None:
        return None

    text = finalize_text(result.text)
    if not text or is_hallucination(
        text,
        no_speech_prob=result.no_speech_prob,
        avg_logprob=result.avg_logprob,
        forced_lang=forced_lang,
        detected_lang=result.language,
    ):
        return None

    lang = decide_language(text, result.language, result.language_prob)
    return {
        "text": text,
        "language": lang,
        "language_prob": round(result.language_prob, 4),
        "duration_sec": round(result.duration, 3),
        "stt_sec": round(time.perf_counter() - started, 3),
    }


def process_audio_pcm(
    pcm: np.ndarray,
    engine: WhisperEngine,
    *,
    language: str = "auto",
    segment: bool = True,
) -> list[dict]:
    """Xử lý mảng PCM 16 kHz mono float32 thành danh sách các câu đã nhận dạng."""
    if pcm.size == 0:
        return []

    forced_lang = None if language == "auto" else language
    chunks: list[np.ndarray] = []

    if segment:
        seg = UtteranceSegmenter()
        for start in range(0, len(pcm), FRAME_SAMPLES):
            chunks.extend(seg.feed(pcm[start : start + FRAME_SAMPLES]))
        tail = seg.flush()
        if tail is not None:
            chunks.append(tail)
        if not chunks:
            chunks = [pcm]
    else:
        chunks = [pcm]

    outputs: list[dict] = []
    for chunk in chunks:
        item = _transcribe_chunk(chunk, engine, forced_lang)
        if item is not None:
            outputs.append(item)
    return outputs


def process_audio_file(
    audio_path: str,
    engine: WhisperEngine,
    *,
    language: str = "auto",
    segment: bool = True,
) -> list[dict]:
    """Đọc file âm thanh bất kỳ (wav/mp3/webm/m4a) và trả về kết quả STT."""
    pcm = load_audio_file(audio_path)
    return process_audio_pcm(pcm, engine, language=language, segment=segment)


def main(argv: list[str] | None = None) -> int:
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="ClassBridge STT Standalone Runner")
    parser.add_argument("--audio", required=True, help="Đường dẫn file âm thanh (.wav, .mp3, .webm, ...)")
    parser.add_argument("--lang", default="auto", choices=["auto", "vi", "en"], help="Ngôn ngữ nhận dạng")
    parser.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda"], help="Thiết bị chạy CT2")
    parser.add_argument("--no-segment", action="store_true", help="Nhận dạng nguyên file thay vì cắt theo câu")
    args = parser.parse_args(argv)

    if not Path(args.audio).is_file():
        print(f"Không tìm thấy file âm thanh: {args.audio}", file=sys.stderr)
        return 2

    engine = WhisperEngine(device=args.device)
    engine.load()

    try:
        results = process_audio_file(
            args.audio,
            engine,
            language=args.lang,
            segment=not args.no_segment,
        )
    except Exception as exc:  # noqa: BLE001 — file hỏng / định dạng ffmpeg không đọc được
        print(f"Không đọc được file âm thanh '{args.audio}': {exc}", file=sys.stderr)
        return 3
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
