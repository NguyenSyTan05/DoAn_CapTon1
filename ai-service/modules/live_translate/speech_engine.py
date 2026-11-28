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
  * Không dùng initial_prompt khi transcribe để tránh Whisper nhại lại prompt lúc im lặng.
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

from modules.live_translate.audio_utils import is_high_freq_noise, preprocess_audio_for_stt

logger = logging.getLogger("classbridge.speech_engine")

_cuda_failed = False  # nhớ lỗi CUDA trong suốt vòng đời tiến trình
_AI_SERVICE_ROOT = Path(__file__).resolve().parents[2]


VI_INITIAL_PROMPT = (
    "Nội dung bài giảng bằng tiếng Việt, có thể có giọng Bắc, Trung hoặc Nam. "
    "Các từ chuyên ngành công nghệ thông tin: deadlock, semaphore, mutex, thread, "
    "cấu trúc dữ liệu, thuật toán, hệ điều hành, lập trình, kiến trúc hệ thống."
)

# Hotwords: truyền vào faster-whisper để boost xác suất các từ dễ bị nhầm.
# Cách hoạt động: Whisper tăng logprob cho token của những từ này trong beam search
# → model tự output đúng, không cần post-process regex thủ công.
VI_HOTWORDS = (
    "độ trễ trước cấu trúc chương trình trực tiếp trọng lực "
    "xử lý xuất sắc hiệu suất giai đoạn "
    "dữ liệu lớp học lập trình viên kiến trúc "
    "deadlock semaphore mutex thread "
    "hệ thống phân tán cơ sở dữ liệu thuật toán "
    "triển khai truy xuất giao diện thông lượng"
)

EN_HOTWORDS = (
    "deadlock semaphore mutex thread process "
    "distributed system database algorithm "
    "latency throughput architecture deployment "
    "structured query language operating system"
)


# Ngưỡng avg_logprob tối thiểu để giữ một đoạn. -0.78 quá gắt với giọng có accent / phòng ồn nên mặc định -1.0.
def _min_logprob() -> float:
    try:
        return float(os.getenv("STT_MIN_LOGPROB", "-1.0"))
    except ValueError:
        return -1.0


def _keep_segment(s, max_no_speech: float = 0.85) -> bool:
    if not (getattr(s, "text", "") or "").strip():
        return False
    nsp = float(getattr(s, "no_speech_prob", 0.0) or 0.0)
    lp = float(getattr(s, "avg_logprob", 0.0) or 0.0)
    cr = float(getattr(s, "compression_ratio", 0.0) or 0.0)
    if nsp >= max_no_speech:
        return False
    if cr > 2.4:
        return False  # chuỗi lặp (temperature=0 không có fallback)
    if lp < _min_logprob():
        return False  # tiếng xì xào nền / tạp âm phòng họp có độ tự tin rất thấp
    if nsp >= 0.60 and lp < -0.55:
        return False  # vừa nghi không có tiếng nói vừa logprob thấp
    return True


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

    candidates: list[Path] = [
        Path(sys.prefix) / "Lib" / "site-packages" / "torch" / "lib",
        _AI_SERVICE_ROOT / ".venv" / "Lib" / "site-packages" / "torch" / "lib",
        _AI_SERVICE_ROOT.parent / ".venv" / "Lib" / "site-packages" / "torch" / "lib",
        _AI_SERVICE_ROOT.parents[1] / ".venv" / "Lib" / "site-packages" / "torch" / "lib",
    ]
    custom_torch_lib = os.getenv("CLASSBRIDGE_TORCH_LIB_DIR", "").strip()
    if custom_torch_lib:
        candidates.insert(0, Path(custom_torch_lib))
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
        beam_size: int = 2,
        device: str = "auto",
    ) -> None:
        self._explicit_init_path = model_path
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
                if rel_candidate.is_dir() and (rel_candidate / "model.bin").is_file():
                    return str(rel_candidate)
            if os.path.isdir(path) and os.path.isfile(os.path.join(path, "model.bin")):
                return path
        return None

    def _resolve_source(self) -> str:
        local_turbo = self._first_existing_dir([
            _AI_SERVICE_ROOT / "trained_models" / "stt" / "whisper-large-v3-turbo-ct2",
        ])
        has_local_turbo = bool(local_turbo and os.path.isfile(os.path.join(local_turbo, "model.bin")))

        # Nếu .env cũ còn lưu đường dẫn model_vi_ct2 (bị lỗi nhãn manifest) trong khi đã có Large-v3-Turbo,
        # tự động ưu tiên Large-v3-Turbo trừ khi cố ý bật WHISPER_FORCE_LEGACY_CT2=1 hoặc truyền trực tiếp qua code.
        is_legacy_env_ct2 = (
            self._explicit_init_path is None
            and self.model_path is not None
            and any(k in self.model_path.replace("\\", "/").lower() for k in ("model_vi_ct2", "decoder-micro1"))
            and os.getenv("WHISPER_FORCE_LEGACY_CT2") != "1"
        )
        if has_local_turbo and (self.model_path is None or is_legacy_env_ct2):
            return str(local_turbo)

        # 1. Nếu người dùng chủ động đặt model_path khác thì tôn trọng
        explicit = self._first_existing_dir([self.model_path])
        if explicit:
            return explicit
        if self.model_path and "/" in self.model_path:
            try:
                from huggingface_hub import snapshot_download

                return snapshot_download(self.model_path, local_files_only=True)
            except Exception:
                pass
        if self.model_path:
            logger.warning("WHISPER_MODEL_PATH không tồn tại (%s), chuyển sang model chuẩn.", self.model_path)

        if has_local_turbo:
            return str(local_turbo)

        hf_override = os.getenv("WHISPER_HF_REPO", "").strip()
        for hf_repo in ((hf_override,) if hf_override else ()) + (
            "deepdml/faster-whisper-large-v3-turbo-ct2",
            "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
            "Systran/faster-whisper-small",
        ):
            try:
                from huggingface_hub import snapshot_download

                return snapshot_download(hf_repo, local_files_only=True)
            except Exception:
                continue

        local_fallback = self._first_existing_dir([
            os.getenv("WHISPER_FALLBACK_MODEL_DIR"),
            _AI_SERVICE_ROOT / "trained_models" / "stt" / "model_vi_ct2",
        ])
        if local_fallback:
            return local_fallback
        return hf_override or "deepdml/faster-whisper-large-v3-turbo-ct2"

    def _resolve_en_source(self) -> str | None:
        # Khi model chính đã là Large-v3-Turbo thì dùng chung luôn cho cả tiếng Anh (809M chuẩn hơn hẳn model_en_ct2 74M)
        if self._vi_source and "large-v3-turbo" in self._vi_source.lower() and os.getenv("WHISPER_FORCE_LEGACY_CT2") != "1":
            return None
        if not self.en_model_path:
            return None
        return self._first_existing_dir([self.en_model_path])

    def _device_candidates(self) -> list[tuple[str, str]]:
        global _cuda_failed
        candidates: list[tuple[str, str]] = []
        # Đã thử CUDA và lỗi (thiếu cuBLAS/cuDNN) thì không thử lại trong cùng tiến trình:
        # đo thực tế thấy nạp CUDA lần thứ hai sau khi lỗi có thể treo.
        if self.requested_device in ("auto", "cuda") and not _cuda_failed:
            try:
                import ctranslate2

                if ctranslate2.get_cuda_device_count() > 0 and _has_cublas12():
                    # int8_float16 (~820 MB VRAM cho Large-v3-Turbo) chạy mượt cùng NLLB-200 trên RTX 3050 4GB;
                    # kèm float16 dự phòng nếu model CT2 không đóng gói int8
                    candidates.append(("cuda", "int8_float16"))
                    candidates.append(("cuda", "float16"))
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
                if device == "cuda" and compute_type == "float16":
                    _cuda_failed = True
                logger.warning("WhisperEngine không dùng được %s/%s cho %s: %s", device, compute_type, source, exc)
        raise RuntimeError(f"Không nạp được model Whisper ({source}) trên bất kỳ thiết bị nào")

    def _enough_free_ram_for_second_model(self) -> bool:
        """Nạp model thứ 2 trên CPU khi RAM gần cạn có thể gây mkl_malloc failed trên máy 8 GB.
        Trên CUDA trọng số nằm trong VRAM (~150 MB) nên chỉ cần ~300 MB RAM đệm lúc đọc file."""
        default_min = "300" if self.device == "cuda" else "700"
        min_free_mb = int(os.getenv("WHISPER_EN_MIN_FREE_MB", default_min))
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

        # Trên CUDA nạp sẵn luôn model EN (~145 MB VRAM) để chế độ Auto và EN không bị khựng lần đầu
        should_preload_en = (
            preload_en
            or self.device == "cuda"
            or os.getenv("WHISPER_PRELOAD_EN") == "1"
        ) and os.getenv("WHISPER_PRELOAD_EN") != "0"
        if should_preload_en:
            self._ensure_en_model()

    def _decode_with_model(
        self,
        active_model,
        processed: np.ndarray,
        lang: str | None,
        effective_beam: int,
        max_no_speech: float = 0.85,
    ) -> tuple[list, object]:
        vad_opts = {
            "threshold": 0.34,
            "min_speech_duration_ms": 140,
            "min_silence_duration_ms": 300,
            "speech_pad_ms": 350,
        }
        segments, info = active_model.transcribe(
            processed,
            language=lang,
            beam_size=effective_beam,
            best_of=1,
            temperature=0.0,
            condition_on_previous_text=False,
            repetition_penalty=1.12,
            no_repeat_ngram_size=3,
            without_timestamps=True,
            initial_prompt=VI_INITIAL_PROMPT if lang == "vi" else None,
            hotwords=VI_HOTWORDS if lang == "vi" else (EN_HOTWORDS if lang == "en" else None),
            compression_ratio_threshold=2.4,
            log_prob_threshold=_min_logprob(),
            no_speech_threshold=0.85,
            vad_filter=True,
            vad_parameters=vad_opts,
        )
        kept = [s for s in segments if _keep_segment(s, max_no_speech=max_no_speech)]
        return kept, info

    # ------------------------------------------------------------------
    def transcribe(self, audio: np.ndarray, language: str | None = None) -> SpeechResult | None:
        if self.model is None:
            raise RuntimeError("Whisper model is not loaded")
        if audio.size == 0:
            return None

        processed = preprocess_audio_for_stt(audio)
        rms = float(np.sqrt(np.mean(processed * processed)))
        peak = float(np.max(np.abs(processed)))
        if (rms < 0.006 and peak < 0.020) or is_high_freq_noise(processed):
            return None

        lang = language if language in ("vi", "en") else None  # None = tự nhận song ngữ VI/EN
        effective_beam = max(5, self.beam_size) if self.device == "cuda" else max(1, min(3, self.beam_size))
        resolved_lang: str | None = lang
        resolved_prob: float = 1.0

        with self._lock:
            if lang in ("vi", "en"):
                actual_lang = lang
                # Nếu người dùng đang chọn cố định VI nhưng lại nói hẳn 1 câu tiếng Anh rõ ràng (hoặc ngược lại),
                # tự động nhận diện để không ép dịch sai âm tiếng Anh sang chữ Việt vô nghĩa
                if hasattr(self.model, "detect_language"):
                    try:
                        _, _, all_probs = self.model.detect_language(processed)
                        probs_map = dict(all_probs or [])
                        p_vi = float(probs_map.get("vi", 0.0))
                        p_en = float(probs_map.get("en", 0.0))
                        if lang == "vi" and p_en >= 0.80 and p_vi < 0.10:
                            actual_lang = "en"
                        elif lang == "en" and p_vi >= 0.80 and p_en < 0.10:
                            actual_lang = "vi"
                    except Exception:
                        pass
                active_model = self._ensure_en_model() if actual_lang == "en" else self.model
                if active_model is None:
                    raise RuntimeError("Whisper model is not loaded")
                kept, info = self._decode_with_model(active_model, processed, actual_lang, effective_beam)
                resolved_lang = actual_lang
                resolved_prob = float(getattr(info, "language_probability", 1.0) or 1.0)
            elif hasattr(self.model, "detect_language"):
                # Gọi detect_language trực tiếp trên mảng audio đã qua segmenter (không truyền dict vad_parameters
                # vì faster-whisper detect_language đòi VadOptions object, truyền dict sẽ văng AttributeError!)
                top_lang, top_prob, all_probs = self.model.detect_language(processed)
                probs_map = dict(all_probs or [])
                p_vi = float(probs_map.get("vi", 0.0))
                p_en = float(probs_map.get("en", 0.0))
                bi_sum = p_vi + p_en

                # Chỉ loại bỏ khi chắc chắn là ngôn ngữ thứ 3 (Hàn/Nhật/Trung >= 70%) và VI+EN rất thấp
                if top_lang not in ("vi", "en") and bi_sum < 0.06 and float(top_prob or 0.0) >= 0.70:
                    return None

                primary_lang = "en" if (top_lang == "en" or p_en > p_vi * 1.15) else "vi"
                primary_model = self._ensure_en_model() if primary_lang == "en" else self.model
                if primary_model is None:
                    raise RuntimeError("Whisper model is not loaded")

                strict_non_bi = top_lang not in ("vi", "en") and bi_sum < 0.08 and float(top_prob or 0.0) >= 0.55
                kept, info = self._decode_with_model(
                    primary_model,
                    processed,
                    primary_lang,
                    effective_beam,
                    max_no_speech=0.60 if strict_non_bi else 0.85,
                )
                avg_lp = (
                    sum(float(getattr(s, "avg_logprob", 0.0) or 0.0) for s in kept) / len(kept)
                    if kept
                    else -99.0
                )

                en_model_ref = self._ensure_en_model()
                if abs(p_en - p_vi) < 0.20 and (not kept or avg_lp < -0.78):
                    alt_lang = "vi" if primary_lang == "en" else "en"
                    alt_model = (en_model_ref if en_model_ref is not None else self.model) if alt_lang == "en" else self.model
                    if alt_model is not None:
                        alt_kept, alt_info = self._decode_with_model(
                            alt_model, processed, alt_lang, effective_beam,
                            max_no_speech=0.60 if strict_non_bi else 0.85,
                        )
                        alt_lp = (
                            sum(float(getattr(s, "avg_logprob", 0.0) or 0.0) for s in alt_kept) / len(alt_kept)
                            if alt_kept
                            else -99.0
                        )
                        if alt_kept and alt_lp > avg_lp + 0.10:
                            kept, info, primary_lang, avg_lp = alt_kept, alt_info, alt_lang, alt_lp

                if strict_non_bi and avg_lp < -1.10:
                    return None

                resolved_lang = primary_lang
                resolved_prob = (
                    (p_en if primary_lang == "en" else p_vi) / bi_sum
                    if bi_sum > 1e-6
                    else float(top_prob or 0.0)
                )
            else:
                # Nhánh dự phòng khi dùng mock/engine không có detect_language
                kept, info = self._decode_with_model(self.model, processed, None, effective_beam)
                det_lang = getattr(info, "language", None)
                det_prob = float(getattr(info, "language_probability", 0.0) or 0.0)
                if kept and det_lang not in ("vi", "en"):
                    if det_prob < 0.35:
                        return None
                    kept, info = self._decode_with_model(
                        self.model, processed, "vi", effective_beam, max_no_speech=0.45
                    )
                    if kept and (sum(float(getattr(s, "avg_logprob", 0.0) or 0.0) for s in kept) / len(kept)) < -0.85:
                        return None
                    det_lang = "vi"
                resolved_lang = det_lang
                resolved_prob = det_prob

        if not kept:
            return None
        return SpeechResult(
            text=" ".join(s.text.strip() for s in kept),
            language=resolved_lang or getattr(info, "language", None),
            language_prob=resolved_prob,
            no_speech_prob=max(float(getattr(s, "no_speech_prob", 0.0)) for s in kept),
            avg_logprob=sum(float(getattr(s, "avg_logprob", 0.0)) for s in kept) / len(kept),
            duration=float(getattr(info, "duration", 0.0) or 0.0),
        )
