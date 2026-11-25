from __future__ import annotations

import threading
from typing import Any

from huggingface_hub import snapshot_download
from huggingface_hub.errors import LocalEntryNotFoundError

from modules.live_translate.text_filters import decide_language


class AiService:
    """Owns the shared NLLB-200 MT model for the lifetime of one process.

    STT do `WhisperEngine` (speech_engine.py) đảm nhiệm riêng để có khóa độc lập
    và chạy song song với dịch máy.
    """

    def __init__(self) -> None:
        self.device = "cpu"
        self.model_lock = threading.Lock()
        self.nllb_tokenizer = None
        self.nllb_model: Any = None
        self.nllb_lang_map = {"en": "eng_Latn", "vi": "vie_Latn"}

    def load_models(self, load_stt: bool = False) -> None:
        """Load NLLB-200 once. Called from the FastAPI lifespan."""
        del load_stt  # Giữ tham số tương thích lời gọi cũ; STT do WhisperEngine nạp riêng.
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        device = "cuda" if torch.cuda.is_available() else "cpu"
        with self.model_lock:
            self.device = device
            if self.nllb_model is not None:
                return

        nllb_id = "facebook/nllb-200-distilled-600M"
        try:
            nllb_source = snapshot_download(nllb_id, local_files_only=True)
        except LocalEntryNotFoundError:
            nllb_source = nllb_id

        nllb_dtype = torch.float16 if device == "cuda" else torch.float32
        nllb_tokenizer = AutoTokenizer.from_pretrained(nllb_source)
        nllb_model = AutoModelForSeq2SeqLM.from_pretrained(
            nllb_source,
            use_safetensors=False,
            low_cpu_mem_usage=True,
            torch_dtype=nllb_dtype,
        ).to(device)
        nllb_model.eval()
        try:
            nllb_tokenizer.src_lang = "vie_Latn"
            warm_in = nllb_tokenizer("Xin chào", return_tensors="pt").to(device)
            warm_bos = nllb_tokenizer.convert_tokens_to_ids("eng_Latn")
            with torch.inference_mode():
                nllb_model.generate(**warm_in, forced_bos_token_id=warm_bos, max_new_tokens=4)
        except Exception:
            pass

        with self.model_lock:
            if self.nllb_model is None:
                self.nllb_tokenizer = nllb_tokenizer
                self.nllb_model = nllb_model

    def transcript_text(self, text: str, src_lang: str, tgt_lang: str) -> str:
        if not text.strip():
            return ""
        if src_lang not in self.nllb_lang_map or tgt_lang not in self.nllb_lang_map:
            raise ValueError("Only English and Vietnamese are supported")
        if self.nllb_tokenizer is None or self.nllb_model is None:
            return ""

        import torch

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
                    max_new_tokens=80,
                    no_repeat_ngram_size=3,
                    use_cache=True,
                )
            return self.nllb_tokenizer.batch_decode(
                generated, skip_special_tokens=True
            )[0].strip()

    @staticmethod
    def detect_language(text: str) -> str:
        return decide_language(text)
