"""
speech_engine.py (modules/live_translate)
===========================================
Lớp STT hoán đổi được (`SpeechEngine`). Hiện có một triển khai: `WhisperEngine`
(faster-whisper / CTranslate2). Muốn dùng model Whisper đã fine-tune của tan-main, chỉ cần
trỏ biến môi trường WHISPER_MODEL_PATH tới thư mục CT2 (có model.bin) — không phải sửa router.

Nguồn gốc (theo CLAUDE.md):
- [EXISTING] faster-whisper, model nền Systran/faster-whisper-small.
- [EXISTING / từ tan-main] tham số giải mã (beam 2, repetition_penalty 1.2, no_repeat_ngram 3,
  Silero VAD có đệm 400 ms, prompt tiếng Việt) trong unified_speech_recognizer.py.
- [CUSTOM — điều chỉnh của nhóm]
  * Chọn thiết bị bằng ctranslate2 và KIỂM TRA thật bằng một lần giải mã thử; nếu thiếu
    cuBLAS/cuDNN thì tự lùi về CPU int8 (bản gốc chọn bằng torch.cuda hoặc chỉ bắt lỗi lúc nạp).
  * Prompt tiếng Việt chỉ dùng khi ép language="vi" (không dùng ở chế độ tự nhận).
  * Cho phép ép ngôn ngữ: bỏ bước nhận diện ngôn ngữ, đo thực tế nhanh ~2 lần trên CPU.
"""

from __future__ import annotations

import gc
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from modules.live_translate.audio_utils import preprocess_audio_for_stt

logger = logging.getLogger("classbridge.speech_engine")

_cuda_failed = False  # nhớ lỗi CUDA trong suốt vòng đời tiến trình
_AI_SERVICE_ROOT = Path(__file__).resolve().parents[2]

VI_INITIAL_PROMPT = (
    "Xin chào các bạn, đây là bài giảng đại học bằng tiếng Việt chuẩn có dấu."
)


@dataclass
class SpeechResult:
    text: str
    language: str | None          # ngôn ngữ Whisper phát hiện/được ép ("en", "vi", ...)
    language_prob: float
    no_speech_prob: float         # lớn nhất trong các đoạn giữ lại
    avg_logprob: float            # trung bình các đoạn giữ lại
    duration: float


class SpeechEngine(Protocol):
    name: str

    def load(self) -> None: ...

    def transcribe(self, audio: np.ndarray, language: str | None = None) -> SpeechResult | None: ...


def _register_cuda_dll_paths() -> None:
    """Bổ sung thư mục torch/lib (chứa cublas64_12.dll, cudnn_ops64_9.dll) vào PATH/DLL search trên Windows."""
    if os.name != "nt":
        return
    import sys

    candidates = [
        Path(sys.prefix) / "Lib" / "site-packages" / "torch" / "lib",
        _AI_SERVICE_ROOT / ".venv" / "Lib" / "site-packages" / "torch" / "lib",
        Path("d:/TailieuNPKH/classbridge/backend/ai-service/.venv/Lib/site-packages/torch/lib"),
    ]
    current_path = os.environ.get("PATH", "")
    for d in candidates:
        if d.is_dir():
            s = str(d)
            if s.lower() not in current_path.lower():
                os.environ["PATH"] = s + os.pathsep + os.environ.get("PATH", "")
                current_path = os.environ["PATH"]
            try:
                os.add_dll_directory(s)
            except Exception:
                pass


def _has_cublas12() -> bool:
    import ctypes.util

    _register_cuda_dll_paths()
    return bool(ctypes.util.find_library("cublas64_12"))


class WhisperEngine:
    name = "faster-whisper"

    def __init__(
        self,
        model_path: str | None = None,
        en_model_path: str | None = None,
        beam_size: int = 1,
        device: str = "auto",
    ) -> None:
        self.model_path = (
            model_path
            or os.getenv("WHISPER_VI_MODEL_PATH")
            or os.getenv("WHISPER_MODEL_PATH")
            or None
        )
        self.en_model_path = en_model_path or os.getenv("WHISPER_EN_MODEL_PATH") or None
        self.beam_size = beam_size
        self.requested_device = os.getenv("WHISPER_DEVICE", device).lower()
        self.device = "cpu"
        self.compute_type = "int8"
        self.model = None
        self.en_model = None
        self._vi_source: str | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    @staticmethod
    def _first_existing_dir(candidates: list[str | Path | None]) -> str | None:
        for raw in candidates:
            if not raw:
                continue
            path = str(raw)
            if not os.path.isabs(path):
                rel_candidate = _AI_SERVICE_ROOT / path
                if rel_candidate.is_dir():
                    return str(rel_candidate)
            if os.path.isdir(path):
                return path
        return None

    def _resolve_source(self) -> str:
        # Cho phép cấu hình trực tiếp repo HuggingFace (VD: "Systran/faster-whisper-small") để độ chính xác tiếng Việt cao hơn dưới tiếng ồn
        if self.model_path and "/" in self.model_path and not os.path.isdir(self.model_path):
            try:
                from huggingface_hub import snapshot_download

                return snapshot_download(self.model_path, local_files_only=True)
            except Exception:
                pass
        found = self._first_existing_dir([
            self.model_path,
            _AI_SERVICE_ROOT / "trained_models" / "stt" / "model_vi_ct2",
            _AI_SERVICE_ROOT / "whisper-decoder-micro1-ct2",
            "d:/TailieuNPKH/classbridge/backend/ai-service/whisper-decoder-micro1-ct2",
        ])
        if found:
            return found
        if self.model_path:
            logger.warning("WHISPER_MODEL_PATH không tồn tại (%s), dùng model nền.", self.model_path)
        try:
            from huggingface_hub import snapshot_download

            return snapshot_download("Systran/faster-whisper-small", local_files_only=True)
        except Exception:
            return "small"  # faster-whisper sẽ tự tải

    def _resolve_en_source(self) -> str | None:
        return self._first_existing_dir([
            self.en_model_path,
            _AI_SERVICE_ROOT / "trained_models" / "stt" / "model_en_ct2",
            "d:/TailieuNPKH/classbridge/training/Module_Train/02_TRAIN_TIENG_ANH/model_en_ct2",
        ])

    def _device_candidates(self) -> list[tuple[str, str]]:
        global _cuda_failed
        candidates: list[tuple[str, str]] = []
        # Đã thử CUDA và lỗi (thiếu cuBLAS/cuDNN) thì không thử lại trong cùng tiến trình:
        # đo thực tế thấy nạp CUDA lần thứ hai sau khi lỗi có thể treo.
        if self.requested_device in ("auto", "cuda") and not _cuda_failed:
            try:
                import ctranslate2

                if ctranslate2.get_cuda_device_count() > 0 and _has_cublas12():
                    # int8_float16 tốn rất ít VRAM (~350 MB) nhưng chạy nhanh gấp ~10 lần CPU trên RTX 3050
                    candidates.append(("cuda", "int8_float16"))
            except Exception:
                pass
        candidates.append(("cpu", "int8"))
        return candidates

    def _load_ct2_model(self, source: str, probe_lang: str):
        from faster_whisper import WhisperModel

        global _cuda_failed
        cpu_threads = min(4, os.cpu_count() or 4)
        probe = np.zeros(16_000, dtype=np.float32)

        for device, compute_type in self._device_candidates():
            model = None
            try:
                model = WhisperModel(
                    source,
                    device=device,
                    compute_type=compute_type,
                    cpu_threads=cpu_threads,
                    num_workers=1,
                )
                # Chỉ cần chạy thử trên CUDA để bắt lỗi thiếu cublas64_12.dll;
                # bỏ qua probe trên CPU để khởi động server nhanh hơn ~10 giây.
                if device == "cuda":
                    list(model.transcribe(probe, language=probe_lang, beam_size=1, without_timestamps=True)[0])
                return model, device, compute_type
            except Exception as exc:  # noqa: BLE001
                del model
                gc.collect()
                if device == "cuda":
                    _cuda_failed = True
                logger.warning("WhisperEngine không dùng được %s/%s cho %s: %s", device, compute_type, source, exc)
        raise RuntimeError(f"Không nạp được model Whisper ({source}) trên bất kỳ thiết bị nào")

    @staticmethod
    def _enough_free_ram_for_second_model() -> bool:
        """Nạp model thứ 2 khi RAM gần cạn có thể làm CTranslate2 crash cả tiến trình
        (đã gặp 'access violation'/'mkl_malloc failed' trên máy 8 GB). Không có psutil thì cho qua."""
        min_free_mb = int(os.getenv("WHISPER_EN_MIN_FREE_MB", "700"))
        try:
            import psutil

            free_mb = psutil.virtual_memory().available // (1024 * 1024)
        except Exception:
            return True
        if free_mb < min_free_mb:
            logger.warning(
                "RAM trống %d MB < %d MB: tạm dùng model chính cho tiếng Anh (sẽ thử lại sau).",
                free_mb, min_free_mb,
            )
            return False
        return True

    def _ensure_en_model(self):
        if self.en_model is not None:
            return self.en_model
        en_source = self._resolve_en_source()
        vi_source = self._vi_source or self._resolve_source()
        if en_source and os.path.abspath(en_source) != os.path.abspath(vi_source):
            if not self._enough_free_ram_for_second_model():
                return self.model  # không ghi nhớ: lần sau RAM đủ sẽ nạp
            try:
                en_model, en_dev, en_ct = self._load_ct2_model(en_source, probe_lang="en")
                self.en_model = en_model
                logger.info("✅ WhisperEngine (EN): %s (%s/%s)", en_source, en_dev, en_ct)
                return self.en_model
            except Exception as exc:  # noqa: BLE001
                logger.warning("Không nạp được model EN riêng (%s), dùng chung model chính: %s", en_source, exc)
        self.en_model = self.model
        return self.en_model

    def load(self, preload_en: bool = False) -> None:
        vi_source = self._resolve_source()
        vi_model, device, compute_type = self._load_ct2_model(vi_source, probe_lang="vi")
        self.model, self.device, self.compute_type = vi_model, device, compute_type
        self._vi_source = vi_source
        logger.info("✅ WhisperEngine (VI/Auto): %s (%s/%s)", vi_source, device, compute_type)

        if preload_en or os.getenv("WHISPER_PRELOAD_EN") == "1":
            self._ensure_en_model()

    # ------------------------------------------------------------------
    def transcribe(self, audio: np.ndarray, language: str | None = None) -> SpeechResult | None:
        if self.model is None:
            raise RuntimeError("Whisper model is not loaded")
        if audio.size == 0:
            return None

        processed = preprocess_audio_for_stt(audio)
        rms = float(np.sqrt(np.mean(processed * processed)))
        peak = float(np.max(np.abs(processed)))
        if rms < 0.002 and peak < 0.01:
            return None

        lang = language if language in ("vi", "en") else None  # None = tự nhận

        with self._lock:
            active_model = self._ensure_en_model() if lang == "en" else self.model
            if active_model is None:
                raise RuntimeError("Whisper model is not loaded")
            segments, info = active_model.transcribe(
                processed,
                language=lang,
                beam_size=self.beam_size,
                best_of=self.beam_size,
                temperature=0.0,
                condition_on_previous_text=False,
                repetition_penalty=1.2,
                no_repeat_ngram_size=3,
                without_timestamps=True,
                initial_prompt=None,
                compression_ratio_threshold=2.4,
                log_prob_threshold=-1.0,
                no_speech_threshold=0.60,
                vad_filter=True,
                vad_parameters={
                    "threshold": 0.45,
                    "min_speech_duration_ms": 200,
                    "min_silence_duration_ms": 350,
                    "speech_pad_ms": 300,
                },
            )
            kept = [
                s for s in segments
                if s.text.strip()
                and getattr(s, "no_speech_prob", 0.0) < 0.60
            ]

        if not kept:
            return None
        return SpeechResult(
            text=" ".join(s.text.strip() for s in kept),
            language=lang or getattr(info, "language", None),
            language_prob=float(getattr(info, "language_probability", 0.0) or 0.0),
            no_speech_prob=max(float(getattr(s, "no_speech_prob", 0.0)) for s in kept),
            avg_logprob=sum(float(getattr(s, "avg_logprob", 0.0)) for s in kept) / len(kept),
            duration=float(getattr(info, "duration", 0.0) or 0.0),
        )
