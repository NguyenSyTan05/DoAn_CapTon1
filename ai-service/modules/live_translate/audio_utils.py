import io

import numpy as np
import static_ffmpeg

static_ffmpeg.add_paths()

from pydub import AudioSegment
from pydub.exceptions import CouldntDecodeError

try:
    from scipy.signal import butter, sosfilt

    _HP_SOS = butter(4, 90.0, btype="highpass", fs=16_000, output="sos")
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
        audio = AudioSegment.from_file(source, format="webm")
    except CouldntDecodeError:
        source.seek(0)
        try:
            audio = AudioSegment.from_file(source)
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
    audio = AudioSegment.from_file(file_path)
    return _segment_to_pcm32(audio)


def preprocess_audio_for_stt(
    audio: np.ndarray,
    *,
    target_rms: float = 0.08,
    min_speech_rms: float = 0.010,
    max_gain: float = 3.5,
) -> np.ndarray:
    """Sanitize PCM, strip <90Hz hum/fan noise, and gently normalize speech without boosting silence."""
    arr = np.asarray(audio)
    if arr.size == 0:
        return np.empty(0, dtype=np.float32)
    if arr.ndim > 1:
        # (n, channels) hoặc (channels, n): gộp về mono theo trục ngắn hơn
        arr = arr.mean(axis=int(np.argmin(arr.shape)))
    if np.issubdtype(arr.dtype, np.integer):
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
        samples = np.asarray(sosfilt(_HP_SOS, samples), dtype=np.float32)
    rms = float(np.sqrt(np.mean(samples * samples)))
    if rms >= min_speech_rms and rms < target_rms:
        peak = float(np.max(np.abs(samples)))
        safe_peak_gain = 0.95 / peak if peak > 1e-6 else max_gain
        gain = min(target_rms / rms, max_gain, safe_peak_gain)
        if gain > 1.0:
            samples = samples * gain

    return np.ascontiguousarray(np.clip(samples, -1.0, 1.0), dtype=np.float32)
