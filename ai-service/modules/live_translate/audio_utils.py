import io
from typing import cast

import numpy as np
import static_ffmpeg

static_ffmpeg.add_paths()

from pydub import AudioSegment
from pydub.exceptions import CouldntDecodeError

try:
    from scipy.signal import butter, sosfilt

    _HP_SOS: np.ndarray | None = np.asarray(
        butter(4, 80.0, btype="highpass", fs=16_000, output="sos"),
        dtype=np.float64,
    )
except Exception:
    _HP_SOS = None
    sosfilt = None


# Browser chunks are short WebM/Opus recordings. Bound input before ffmpeg
# expands it into PCM so a malformed upload cannot exhaust process memory.
MAX_AUDIO_BYTES = 8 * 1024 * 1024
MAX_DURATION_SECONDS = 15.0
TARGET_SAMPLE_RATE = 16_000

def _segment_to_pcm32(audio: AudioSegment) -> np.ndarray:
    """Convert a pydub AudioSegment to contiguous 16 kHz mono float32 PCM."""
    audio = audio.set_frame_rate(TARGET_SAMPLE_RATE).set_channels(1)
    if audio.sample_width <= 0:
        return np.empty(0, dtype=np.float32)

    samples = np.asarray(audio.get_array_of_samples(), dtype=np.float32)
    scale = float(1 << (8 * audio.sample_width - 1))
    samples = np.clip(samples / scale, -1.0, 1.0)
    samples = np.nan_to_num(samples, nan=0.0, posinf=0.0, neginf=0.0)
    return np.ascontiguousarray(samples, dtype=np.float32)


def xuly_am_thanh(file_bytes: bytes) -> np.ndarray:
    """Decode a browser WebM chunk into contiguous 16 kHz mono float32 PCM."""
    if not file_bytes:
        return np.empty(0, dtype=np.float32)
    if len(file_bytes) > MAX_AUDIO_BYTES:
        raise ValueError(f"Audio chunk exceeds {MAX_AUDIO_BYTES} bytes")

    source = io.BytesIO(file_bytes)
    try:
        audio = cast(AudioSegment, AudioSegment.from_file(source, format="webm"))
    except CouldntDecodeError:
        source.seek(0)
        try:
            audio = cast(AudioSegment, AudioSegment.from_file(source))
        except CouldntDecodeError as exc:
            raise ValueError("Unable to decode audio chunk") from exc

    if audio.duration_seconds > MAX_DURATION_SECONDS:
        raise ValueError(f"Audio chunk exceeds {MAX_DURATION_SECONDS} seconds")

    return _segment_to_pcm32(audio)


def decode_pcm16(data: bytes) -> np.ndarray:
    """Decode raw 16-bit signed little-endian PCM into contiguous float32 [-1, 1]."""
    if not data:
        return np.empty(0, dtype=np.float32)
    usable = len(data) - (len(data) % 2)
    if usable <= 0:
        return np.empty(0, dtype=np.float32)
    samples = np.frombuffer(data[:usable], dtype=np.int16).astype(np.float32) / 32768.0
    return np.ascontiguousarray(np.clip(samples, -1.0, 1.0), dtype=np.float32)


def decode_pcm32(data: bytes) -> np.ndarray:
    """Decode raw 32-bit float PCM into sanitized contiguous float32 [-1, 1]."""
    if not data:
        return np.empty(0, dtype=np.float32)
    usable = len(data) - (len(data) % 4)
    if usable <= 0:
        return np.empty(0, dtype=np.float32)
    samples = np.nan_to_num(
        np.frombuffer(data[:usable], dtype=np.float32).copy(),
        nan=0.0,
        posinf=0.0,
        neginf=0.0,
    )
    return np.ascontiguousarray(np.clip(samples, -1.0, 1.0), dtype=np.float32)


def load_audio_file(file_path: str) -> np.ndarray:
    """Load an audio file (wav/mp3/webm/m4a/ogg) into 16 kHz mono float32 PCM."""
    audio = cast(AudioSegment, AudioSegment.from_file(file_path))
    return _segment_to_pcm32(audio)


def is_high_freq_noise(samples: np.ndarray, sample_rate: int = TARGET_SAMPLE_RATE) -> bool:
    """True nếu tín hiệu là nhiễu trắng/tiếng rít thuần túy (năng lượng > 4 kHz cao bất thường
    đồng thời thiếu năng lượng dải formant giọng người 120–3500 Hz)."""
    if samples.size < 512:
        return False
    spec = np.abs(np.fft.rfft(samples)) ** 2
    total = float(np.sum(spec))
    if total <= 1e-12:
        return True
    freqs = np.fft.rfftfreq(samples.size, d=1.0 / sample_rate)
    high_energy = float(np.sum(spec[freqs > 4000.0]))
    voice_energy = float(np.sum(spec[(freqs >= 120.0) & (freqs <= 3500.0)]))
    return (high_energy / total) > 0.46 and (voice_energy / total) < 0.45


def preprocess_audio_for_stt(
    audio: np.ndarray,
    *,
    target_rms: float = 0.09,
    min_speech_rms: float = 0.005,
    max_gain: float = 4.0,
) -> np.ndarray:
    """Sanitize PCM, strip <80Hz hum/fan noise, and gently normalize speech without boosting silence/noise."""
    arr = np.asarray(audio)
    if arr.size == 0:
        return np.empty(0, dtype=np.float32)
    if arr.ndim > 1:
        # (n, channels) hoặc (channels, n): gộp về mono theo trục ngắn hơn
        arr = arr.mean(axis=int(np.argmin(arr.shape)))
    if np.issubdtype(arr.dtype, np.unsignedinteger):
        # uint8 (0..255, tâm 128) -> [-1, 1]
        mid = float(np.iinfo(arr.dtype).max + 1) / 2.0
        arr = (arr.astype(np.float32) - mid) / mid
    elif np.issubdtype(arr.dtype, np.integer):
        # int16/int32 thô -> [-1, 1] (nếu không, clip sẽ biến mọi mẫu thành ±1)
        arr = arr.astype(np.float32) / float(np.iinfo(arr.dtype).max + 1)

    samples = np.nan_to_num(
        arr.astype(np.float32, copy=False).ravel(),
        nan=0.0,
        posinf=0.0,
        neginf=0.0,
    )
    samples = samples - float(np.mean(samples))
    if _HP_SOS is not None and sosfilt is not None and samples.size >= 32:
        samples = np.asarray(sosfilt(_HP_SOS, samples), dtype=np.float64).astype(np.float32)
    rms = float(np.sqrt(np.mean(samples * samples)))
    peak = float(np.max(np.abs(samples)))
    # Không khuếch đại khoảng lặng hoặc tiếng rít/nhiễu tần số cao
    if rms >= min_speech_rms and peak >= 0.016 and rms < target_rms and not is_high_freq_noise(samples):
        safe_peak_gain = 0.95 / peak if peak > 1e-6 else max_gain
        gain = min(target_rms / rms, max_gain, safe_peak_gain)
        if gain > 1.0:
            samples = samples * gain

    return np.ascontiguousarray(np.clip(samples, -1.0, 1.0), dtype=np.float32)
