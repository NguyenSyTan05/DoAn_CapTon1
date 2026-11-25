"""Unit tests cho pipeline STT & xử lý âm thanh (không nạp model thật)."""

from __future__ import annotations

import struct
from types import SimpleNamespace

import numpy as np

from modules.live_translate.audio_utils import (
    decode_pcm16,
    decode_pcm32,
    is_high_freq_noise,
    preprocess_audio_for_stt,
)
from modules.live_translate.segmenter import FRAME_SAMPLES, SAMPLE_RATE, UtteranceSegmenter
from modules.live_translate.speech_engine import WhisperEngine, _keep_segment
from modules.live_translate.text_filters import (
    clean_transcript_text,
    decide_language,
    is_decoder_loop,
    is_hallucination,
)


def _sine(freq_hz: float = 440.0, amp: float = 0.2, seconds: float = 1.0) -> np.ndarray:
    t = np.arange(int(SAMPLE_RATE * seconds), dtype=np.float32) / SAMPLE_RATE
    return (amp * np.sin(2.0 * np.pi * freq_hz * t)).astype(np.float32)


def _seg(
    text: str = "Xin chào",
    *,
    no_speech_prob: float = 0.1,
    avg_logprob: float = -0.3,
    compression_ratio: float = 1.2,
) -> SimpleNamespace:
    return SimpleNamespace(
        text=text,
        no_speech_prob=no_speech_prob,
        avg_logprob=avg_logprob,
        compression_ratio=compression_ratio,
    )


class _FakeWhisperModel:
    def __init__(self, responses: list[tuple[list[SimpleNamespace], SimpleNamespace]]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    def transcribe(self, audio: np.ndarray, **kwargs):
        self.calls.append({"len": len(audio), **kwargs})
        return self._responses.pop(0)


def test_is_decoder_loop() -> None:
    assert is_decoder_loop("live live live live") is True
    assert is_decoder_loop("Hello, hello, hello, hello!") is True
    assert is_decoder_loop("a b a b a b") is True
    assert is_decoder_loop("luôn luôn đúng") is False
    assert is_decoder_loop("từ từ thôi") is False
    assert is_decoder_loop("Hôm nay chúng ta học về deadlock") is False
    assert is_decoder_loop("") is False


def test_is_hallucination_preserves_math_and_blocks_noise() -> None:
    assert is_hallucination("x = 5", no_speech_prob=0.1, avg_logprob=-0.2) is False
    assert is_hallucination("a + b = c", no_speech_prob=0.1, avg_logprob=-0.2) is False
    assert is_hallucination("Ú, ơ.", no_speech_prob=0.1, avg_logprob=-0.2) is True
    assert is_hallucination("A", no_speech_prob=0.1, avg_logprob=-0.2) is True
    assert is_hallucination("Thank you", no_speech_prob=0.0, avg_logprob=-0.1, forced_lang="vi") is True
    assert is_hallucination("Thank you.", no_speech_prob=0.0, avg_logprob=-0.1, forced_lang="en") is True
    assert is_hallucination("Cảm ơn các bạn.", no_speech_prob=0.0, avg_logprob=-0.1, forced_lang="vi") is True
    assert is_hallucination("Cám ơn các bạn", no_speech_prob=0.0, avg_logprob=-0.1) is True
    assert is_hallucination("Xin chào các bạn.", no_speech_prob=0.0, avg_logprob=-0.1) is True
    assert is_hallucination("Cảm ơn các bạn đã theo dõi", no_speech_prob=0.05, avg_logprob=-0.1) is True
    assert is_hallucination("Cảm ơn mọi người đã lắng nghe!", no_speech_prob=0.05, avg_logprob=-0.1) is True
    assert is_hallucination("Cảm ơn bạn.", no_speech_prob=0.05, avg_logprob=-0.1) is True
    assert is_hallucination("Thank you for listening", no_speech_prob=0.05, avg_logprob=-0.1) is True
    assert is_hallucination("Cảm ơn em đã đặt câu hỏi về deadlock.", no_speech_prob=0.05, avg_logprob=-0.2) is False


def test_clean_transcript_text_punctuation_and_sound_tags() -> None:
    assert clean_transcript_text("[Music] ♪") == ""
    assert clean_transcript_text("(âm nhạc)   ") == ""
    assert clean_transcript_text(", xin chào.. ") == "Xin chào."
    assert clean_transcript_text("hôm nay,học về Node.js lúc 10:30.") == "Hôm nay, học về Node.js lúc 10:30."
    assert clean_transcript_text("đúng không??") == "Đúng không?"
    assert clean_transcript_text("http://localhost:4000") == "http://localhost:4000"


def test_decide_language() -> None:
    assert decide_language("café résumé naïve", whisper_lang="en") == "en"
    assert decide_language("là và có", whisper_lang="en") == "vi"
    assert decide_language("Tôi tên là Tân", whisper_lang="en") == "vi"
    assert decide_language("Hello, what's your name?", whisper_lang="vi") == "en"
    assert decide_language("Deadlock là gì ạ?") == "vi"
    assert decide_language("What is a deadlock?") == "en"


def test_keep_segment() -> None:
    assert _keep_segment(_seg("ok", no_speech_prob=0.1, avg_logprob=-0.3, compression_ratio=1.2)) is True
    assert _keep_segment(_seg("ok", no_speech_prob=0.52, avg_logprob=-0.4, compression_ratio=1.2)) is True
    assert _keep_segment(_seg("ok", no_speech_prob=0.72, avg_logprob=-0.3, compression_ratio=1.2)) is False
    assert _keep_segment(_seg("ok", no_speech_prob=0.1, avg_logprob=-0.3, compression_ratio=2.6)) is False
    assert _keep_segment(_seg("ok", no_speech_prob=0.55, avg_logprob=-1.05, compression_ratio=1.2)) is False
    assert _keep_segment(_seg("ok", no_speech_prob=0.1, avg_logprob=-1.45, compression_ratio=1.2)) is False
    assert _keep_segment(_seg("   ", no_speech_prob=0.1, avg_logprob=-0.3, compression_ratio=1.2)) is False


def test_whisper_engine_skips_silence_and_filters_segments() -> None:
    engine = WhisperEngine(device="cpu")
    fake = _FakeWhisperModel([])
    engine.model = fake
    engine.device = "cpu"

    assert engine.transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32)) is None
    assert len(fake.calls) == 0

    sine = _sine()

    fake_hall = _FakeWhisperModel([
        ([_seg("thank you", no_speech_prob=0.5, avg_logprob=-1.5, compression_ratio=1.1)],
         SimpleNamespace(language="en", language_probability=0.9, duration=1.0)),
    ])
    engine.model = fake_hall
    assert engine.transcribe(sine) is None

    fake_good = _FakeWhisperModel([
        ([_seg("Xin chào các em.", no_speech_prob=0.05, avg_logprob=-0.2, compression_ratio=1.1)],
         SimpleNamespace(language="vi", language_probability=0.95, duration=1.0)),
    ])
    engine.model = fake_good
    res = engine.transcribe(sine)
    assert res is not None
    assert res.text == "Xin chào các em."
    assert res.language == "vi"


def test_whisper_engine_auto_redecode_vi_threshold() -> None:
    sine = _sine()
    engine = WhisperEngine(device="cpu")
    engine.device = "cpu"

    # Lần 1 ra 'fr' prob 0.8; lần 2 ép 'vi' có avg_logprob=-0.9 (< -0.8) -> None
    engine.model = _FakeWhisperModel([
        ([_seg("bonjour", no_speech_prob=0.1, avg_logprob=-0.3, compression_ratio=1.1)],
         SimpleNamespace(language="fr", language_probability=0.8, duration=1.0)),
        ([_seg("bịa chữ", no_speech_prob=0.1, avg_logprob=-0.9, compression_ratio=1.1)],
         SimpleNamespace(language="vi", language_probability=1.0, duration=1.0)),
    ])
    assert engine.transcribe(sine, language=None) is None

    # Lần 2 ép 'vi' có avg_logprob=-0.3 -> giữ lại với language='vi'
    engine.model = _FakeWhisperModel([
        ([_seg("bonjour", no_speech_prob=0.1, avg_logprob=-0.3, compression_ratio=1.1)],
         SimpleNamespace(language="fr", language_probability=0.8, duration=1.0)),
        ([_seg("Xin chào", no_speech_prob=0.1, avg_logprob=-0.3, compression_ratio=1.1)],
         SimpleNamespace(language="vi", language_probability=1.0, duration=1.0)),
    ])
    res = engine.transcribe(sine, language=None)
    assert res is not None
    assert res.language == "vi"
    assert res.text == "Xin chào"


def test_whisper_engine_bilingual_auto_routes_to_en_model() -> None:
    sine = _sine()
    engine = WhisperEngine(device="cpu")
    engine.device = "cpu"

    class _DetectableFakeModel(_FakeWhisperModel):
        def __init__(self, det_result, responses) -> None:
            super().__init__(responses)
            self._det_result = det_result

        def detect_language(self, audio: np.ndarray):
            del audio
            return self._det_result

    # Khi nói tiếng Anh ở chế độ Auto (kể cả xác suất tổng chỉ 0.38 do chia sẻ với các ngôn ngữ châu Âu),
    # engine phải định tuyến sang en_model thay vì ép model_vi_ct2 giải mã hoặc vứt bỏ câu.
    vi_fake = _DetectableFakeModel(
        ("en", 0.38, [("en", 0.38), ("vi", 0.04), ("de", 0.15)]),
        [],
    )
    en_fake = _FakeWhisperModel([
        ([_seg("Hello, what is your name?", no_speech_prob=0.08, avg_logprob=-0.25, compression_ratio=1.1)],
         SimpleNamespace(language="en", language_probability=1.0, duration=1.5)),
    ])
    engine.model = vi_fake
    engine.en_model = en_fake
    res_en = engine.transcribe(sine, language=None)
    assert res_en is not None
    assert res_en.language == "en"
    assert res_en.text == "Hello, what is your name?"
    assert len(vi_fake.calls) == 0
    assert len(en_fake.calls) == 1 and en_fake.calls[0]["language"] == "en"

    # Khi tạp âm tiếng nước ngoài (ko=0.80, vi+en < 0.12) -> loại bỏ ngay, không tốn decode
    noise_fake = _DetectableFakeModel(
        ("ko", 0.80, [("ko", 0.80), ("vi", 0.02), ("en", 0.03)]),
        [],
    )
    engine.model = noise_fake
    assert engine.transcribe(sine, language=None) is None
    assert len(noise_fake.calls) == 0


def test_utterance_segmenter() -> None:
    silence = np.zeros(FRAME_SAMPLES, dtype=np.float32)
    t_frame = np.arange(FRAME_SAMPLES, dtype=np.float32) / SAMPLE_RATE
    speech = (0.15 * np.sin(2.0 * np.pi * 300.0 * t_frame)).astype(np.float32)
    hum60 = (0.06 * np.sin(2.0 * np.pi * 60.0 * t_frame)).astype(np.float32)
    dc = np.full(FRAME_SAMPLES, 0.2, dtype=np.float32)

    seg = UtteranceSegmenter()
    for _ in range(15):
        assert seg.feed(silence) == []
    assert seg.flush() is None

    # Tiếng ù 60 Hz và DC offset không được kích hoạt segmenter
    seg_hum = UtteranceSegmenter()
    for _ in range(20):
        assert seg_hum.feed(hum60) == []
    assert seg_hum.flush() is None

    seg_dc = UtteranceSegmenter()
    for _ in range(20):
        assert seg_dc.feed(dc) == []
    assert seg_dc.flush() is None

    # Click 100 ms rồi im lặng -> bỏ
    seg2 = UtteranceSegmenter()
    assert seg2.feed(speech) == []
    for _ in range(10):
        assert seg2.feed(silence) == []
    assert seg2.flush() is None

    # 1.0 s giọng nói rồi 0.8 s im lặng -> đúng 1 câu
    seg3 = UtteranceSegmenter()
    utts: list[np.ndarray] = []
    for _ in range(10):
        utts.extend(seg3.feed(speech))
    for _ in range(8):
        utts.extend(seg3.feed(silence))
    assert len(utts) == 1


def test_high_freq_noise_filter() -> None:
    rng = np.random.default_rng(7)
    white = rng.normal(0.0, 0.05, SAMPLE_RATE).astype(np.float32)
    voice = _sine(300.0, amp=0.15, seconds=1.0)
    assert is_high_freq_noise(white) is True
    assert is_high_freq_noise(voice) is False

    engine = WhisperEngine(device="cpu")
    fake = _FakeWhisperModel([])
    engine.model = fake
    engine.device = "cpu"
    assert engine.transcribe(white) is None
    assert len(fake.calls) == 0


def test_decode_pcm16_and_pcm32() -> None:
    pcm16 = decode_pcm16(b"\x00\x01\x02")
    assert len(pcm16) == 1
    assert pcm16.dtype == np.float32

    raw_pcm32 = struct.pack("<fff", float("nan"), 2.5, -2.5)
    pcm32 = decode_pcm32(raw_pcm32)
    assert len(pcm32) == 3
    assert pcm32[0] == 0.0
    assert float(np.max(pcm32)) <= 1.0
    assert float(np.min(pcm32)) >= -1.0

    # uint8 (0..255) chuẩn hoá về đủ biên độ [-1, 1]
    u8 = np.array([128, 255, 0, 128] * 100, dtype=np.uint8)
    p_u8 = preprocess_audio_for_stt(u8)
    assert float(np.max(np.abs(p_u8))) > 0.85
