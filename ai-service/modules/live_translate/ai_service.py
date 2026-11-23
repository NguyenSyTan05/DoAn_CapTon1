import re
import threading

import numpy as np
import torch
from faster_whisper import WhisperModel
from huggingface_hub import snapshot_download
from huggingface_hub.errors import LocalEntryNotFoundError
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer


VIETNAMESE_DIACRITICS = re.compile(r"[\u00c0-\u1ef9\u0110\u0111]")
WHITESPACE = re.compile(r"\s+")
YOUTUBE_ARTIFACTS = (
    "subscribe",
    "la la school",
    "like and share",
    "like and subscribe",
    "dang ky kenh",
    "đăng ký kênh",
    "hen gap lai",
    "hẹn gặp lại",
    "chia se video",
    "subtitles by amara",
)
SILENCE_HALLUCINATIONS = {
    "thank you",
    "thank you.",
    "cam on",
    "cảm ơn",
    "cảm ơn.",
    "cảm ơn các bạn",
    "i'm not",
    "i am not",
}


class AiService:
    """Owns the shared STT and MT models for the lifetime of one process."""

    def __init__(self) -> None:
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model_lock = threading.Lock()
        self.whisper_model: WhisperModel | None = None
        self.nllb_tokenizer = None
        self.nllb_model: AutoModelForSeq2SeqLM | None = None
        self.nllb_lang_map = {"en": "eng_Latn", "vi": "vie_Latn"}

    def load_models(self, load_stt: bool = True) -> None:
        """Load each model once. This is called from the FastAPI lifespan.

        [CUSTOM] load_stt=False: chỉ nạp NLLB (dịch). STT khi đó do SpeechEngine
        (speech_engine.py) đảm nhiệm, có khóa riêng nên STT và dịch chạy song song."""
        with self.model_lock:
            if (self.whisper_model is not None or not load_stt) and self.nllb_model is not None:
                return

            if load_stt and self.whisper_model is None:
                whisper_compute_type = "float16" if self.device == "cuda" else "int8"
                whisper_id = "Systran/faster-whisper-small"
                try:
                    whisper_source = snapshot_download(whisper_id, local_files_only=True)
                except LocalEntryNotFoundError:
                    whisper_source = "small"

                self.whisper_model = WhisperModel(
                    whisper_source,
                    device=self.device,
                    compute_type=whisper_compute_type,
                )

            nllb_id = "facebook/nllb-200-distilled-600M"
            try:
                nllb_source = snapshot_download(nllb_id, local_files_only=True)
            except LocalEntryNotFoundError:
                nllb_source = nllb_id

            nllb_dtype = torch.float16 if self.device == "cuda" else torch.float32
            self.nllb_tokenizer = AutoTokenizer.from_pretrained(nllb_source)
            self.nllb_model = AutoModelForSeq2SeqLM.from_pretrained(
                nllb_source,
                use_safetensors=False,
                low_cpu_mem_usage=True,
                torch_dtype=nllb_dtype,
            ).to(self.device)
            self.nllb_model.eval()

    def transcript_audio(self, audio_array: np.ndarray) -> tuple[str, str]:
        if self.whisper_model is None:
            raise RuntimeError("Whisper model is not loaded")

        with self.model_lock:
            segments, _ = self.whisper_model.transcribe(
                audio_array,
                # them ham language va intitial_prompt de set
                language = None ,
                beam_size=1,
                temperature=0.0,
                condition_on_previous_text=False,
                repetition_penalty=1.2,
                no_repeat_ngram_size=3,
                no_speech_threshold=0.6,
                compression_ratio_threshold=2.4,
                vad_filter=True,
                vad_parameters={
                    "threshold": 0.5,
                    "min_silence_duration_ms": 400,
                },
            )
            text = WHITESPACE.sub(" ", " ".join(segment.text for segment in segments)).strip()


        if self._is_hallucination(text):
            return "", ""
        return text, self.detect_language(text)

    def transcript_text(self, text: str, src_lang: str, tgt_lang: str) -> str:
        if not text.strip():
            return ""
        if src_lang not in self.nllb_lang_map or tgt_lang not in self.nllb_lang_map:
            raise ValueError("Only English and Vietnamese are supported")
        if self.nllb_tokenizer is None or self.nllb_model is None:
            raise RuntimeError("NLLB model is not loaded")

        with self.model_lock:
            self.nllb_tokenizer.src_lang = self.nllb_lang_map[src_lang]
            inputs = self.nllb_tokenizer(text, return_tensors="pt").to(self.device)
            forced_bos_token_id = self.nllb_tokenizer.convert_tokens_to_ids(
                self.nllb_lang_map[tgt_lang]
            )
            with torch.inference_mode():
                generated = self.nllb_model.generate(
                    **inputs,
                    forced_bos_token_id=forced_bos_token_id,
                    num_beams=1,
                    do_sample=False,
                    max_new_tokens=128,
                    use_cache=True,
                )
            return self.nllb_tokenizer.batch_decode(
                generated, skip_special_tokens=True
            )[0].strip()

    @staticmethod
    def detect_language(text: str) -> str:
        common_vi_words = {"xin", "chao", "toi", "ban", "hoc", "thay", "giang", "vien", "khong", "co"}
        words = set(text.lower().split())
        if VIETNAMESE_DIACRITICS.search(text) or (words & common_vi_words):
            return "vi"
        return "en"

    @staticmethod
    def _is_hallucination(text: str) -> bool:
        normalized = WHITESPACE.sub(" ", text).strip().casefold()
    
    # 1. Kiểm tra chuỗi quá ngắn hoặc nằm trong danh sách rác âm thanh
        if len(normalized) <= 2 or normalized in SILENCE_HALLUCINATIONS:
            return True
        
    # 2. Kiểm tra các câu rác YouTube (như "cảm ơn đã xem", "subscribe"...)
        if any(artifact in normalized for artifact in YOUTUBE_ARTIFACTS):
            return True

    # 3. Phát hiện 1 từ lặp lại liên tiếp từ 3 lần trở lên (VD: "trực trực trực", "live live live")
        if re.search(r'\b(\w+)(?:\s+\1\b){2,}', normalized):
            return True

    # 4. Phát hiện ký tự bị lặp bất thường (VD: "aaaaaa", "......")
        if re.search(r'(.)\1{4,}', normalized):
            return True

    # 5. Kiểm tra độ đa dạng từ vựng (chống lặp cụm dài xen kẽ)
        words = normalized.split()
        if len(words) >= 5:
            unique_words = set(words)
        # Nếu câu dài mà tỷ lệ từ vựng độc nhất < 35% hoặc chỉ xoay quanh 2 từ
            if len(unique_words) / len(words) < 0.35 or len(unique_words) <= 2:
                return True

        return False
