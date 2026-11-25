"""
segmenter.py (modules/live_translate)
=======================================
Cắt luồng PCM thành CÂU NÓI (utterance) theo khoảng lặng, thay cho cửa sổ trượt cố định
2–4 giây của bản cũ (cửa sổ gối nhau nên dễ lặp từ ở chỗ nối).

Nguồn gốc: [EXISTING / từ tan-main] ý tưởng ngưỡng ồn nền thích nghi + pre-roll + cắt theo
khoảng lặng trong main.py::ws_stream. [CUSTOM — điều chỉnh của nhóm]
- Chạy theo khung 100 ms nội bộ nên không phụ thuộc kích thước gói client gửi.
- Khi câu quá dài (>= max_utterance_s) cắt tại điểm năng lượng thấp nhất và KHÔNG gối
  đoạn sau, nên một từ không bị nhận dạng hai lần.
Ngưỡng RMS là giả định cho micro thông thường, cần hiệu chỉnh bằng dữ liệu lớp học thật.
"""

from __future__ import annotations

import numpy as np

try:
    from scipy.signal import butter, sosfilt

    _SEG_HP_SOS: np.ndarray | None = np.asarray(
        butter(4, 110.0, btype="highpass", fs=16_000, output="sos"),
        dtype=np.float64,
    )
except Exception:
    _SEG_HP_SOS = None
    sosfilt = None

SAMPLE_RATE = 16_000
FRAME_SAMPLES = 1_600  # 100 ms


class UtteranceSegmenter:
    def __init__(
        self,
        max_utterance_s: float = 7.5,
        pre_roll_frames: int = 5,
        min_samples: int = 4_000,  # bỏ đoạn < 0.25 s
    ) -> None:
        self.max_samples = int(SAMPLE_RATE * max_utterance_s)
        self.pre_roll_frames = pre_roll_frames
        self.min_samples = min_samples
        self._carry = np.empty(0, dtype=np.float32)  # phần dư chưa đủ 1 khung
        self._pre_roll: list[tuple[np.ndarray, float]] = []
        self._frames: list[np.ndarray] = []
        self._energies: list[float] = []
        self._speech = 0
        self._silence = 0
        self._noise_floor = 0.006
        self._hp_zi = (
            np.zeros((_SEG_HP_SOS.shape[0], 2), dtype=np.float64)
            if _SEG_HP_SOS is not None
            else None
        )

    # ------------------------------------------------------------------
    def feed(self, samples: np.ndarray) -> list[np.ndarray]:
        """Nạp PCM float32 16 kHz; trả về danh sách câu nói đã hoàn thành (có thể rỗng)."""
        if samples.size == 0:
            return []
        buf = np.concatenate([self._carry, samples.astype(np.float32, copy=False)])
        usable = (len(buf) // FRAME_SAMPLES) * FRAME_SAMPLES
        self._carry = buf[usable:]
        out: list[np.ndarray] = []
        for start in range(0, usable, FRAME_SAMPLES):
            utt = self._step(buf[start : start + FRAME_SAMPLES])
            if utt is not None:
                out.append(utt)
        return out

    def flush(self) -> np.ndarray | None:
        """Trả nốt câu đang dở (khi kết thúc phiên / lúc người nói ngắt kết nối)."""
        if self._carry.size:
            self._frames.append(self._carry)
            self._energies.append(self._frame_rms(self._carry))
            self._carry = np.empty(0, dtype=np.float32)
        if self._speech < 2:
            self._reset()
            return None
        return self._emit_all()

    # ------------------------------------------------------------------
    def _emit_all(self) -> np.ndarray | None:
        audio = np.concatenate(self._frames) if self._frames else None
        self._reset()
        if audio is None or len(audio) < self.min_samples:
            return None
        return audio

    def _reset(self) -> None:
        self._frames = []
        self._energies = []
        self._speech = 0
        self._silence = 0

    def _frame_rms(self, frame: np.ndarray) -> float:
        """Đo RMS sau khử DC và lọc thông cao bậc 4 (110 Hz) để bỏ tiếng ù quạt/điều hoà 50–60 Hz."""
        if frame.size == 0:
            return 0.0
        centered = frame.astype(np.float64) - float(np.mean(frame))
        if _SEG_HP_SOS is not None and sosfilt is not None and self._hp_zi is not None:
            filtered, self._hp_zi = sosfilt(_SEG_HP_SOS, centered, zi=self._hp_zi)
            return float(np.sqrt(np.mean(filtered * filtered)))
        return float(np.sqrt(np.mean(centered * centered)))

    def _step(self, frame: np.ndarray) -> np.ndarray | None:
        rms = self._frame_rms(frame)

        # Trạng thái nghỉ: theo dõi ồn nền, giữ 400 ms pre-roll để không mất phụ âm đầu câu
        if not self._frames:
            self._noise_floor = min(0.025, max(0.004, 0.94 * self._noise_floor + 0.06 * rms))
            if rms < max(0.012, self._noise_floor * 1.90):
                self._pre_roll.append((frame, rms))
                if len(self._pre_roll) > self.pre_roll_frames:
                    self._pre_roll.pop(0)
                return None
            self._frames = [f for f, _ in self._pre_roll] + [frame]
            self._energies = [e for _, e in self._pre_roll] + [rms]
            self._pre_roll = []
            self._speech, self._silence = 1, 0
            return None

        # Đang gom câu: dùng ngưỡng duy trì thấp hơn (hysteresis) để không cắt đứt từ nói nhỏ giữa câu
        self._frames.append(frame)
        self._energies.append(rms)
        sustain_th = max(0.006, self._noise_floor * 1.25)
        if rms >= sustain_th:
            self._speech += 1
            self._silence = 0
        else:
            self._silence += 1

        total = len(self._frames) * FRAME_SAMPLES
        if self._speech >= 3 and self._silence >= 5:        # nói >= 300 ms rồi nghỉ 500 ms -> giữ trọn cả câu
            return self._emit_all()
        if self._speech >= 2 and self._silence >= 6:        # từ ngắn ("dạ", "vâng", "ok") + nghỉ 600 ms
            return self._emit_all()
        if self._silence >= 7:                              # xung click 100 ms rồi lặng 700 ms -> bỏ
            return self._drop()
        if total >= self.max_samples:                       # nói liên tục >= 7.5 s -> cắt tại khe lặng
            return self._split_at_dip()
        return None

    def _drop(self) -> None:
        self._reset()
        return None

    def _split_at_dip(self) -> np.ndarray | None:
        frames = self._frames
        energies = self._energies
        lo, hi = max(1, len(frames) - 16), max(2, len(frames) - 2)
        cut = min(range(lo, hi), key=lambda i: energies[i], default=len(frames))
        head = frames[:cut]
        self._frames = frames[cut:]  # không gối đoạn đầu -> không lặp từ
        self._energies = energies[cut:]
        sustain_th = max(0.006, self._noise_floor * 1.25)
        speech_flags = [e >= sustain_th for e in self._energies]
        self._speech = sum(1 for ok in speech_flags if ok)
        trailing_silence = 0
        for ok in reversed(speech_flags):
            if ok:
                break
            trailing_silence += 1
        self._silence = trailing_silence
        audio = np.concatenate(head) if head else None
        if audio is None or len(audio) < self.min_samples:
            return None
        return audio
