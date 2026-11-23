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

SAMPLE_RATE = 16_000
FRAME_SAMPLES = 1_600  # 100 ms


class UtteranceSegmenter:
    def __init__(
        self,
        max_utterance_s: float = 6.0,
        pre_roll_frames: int = 3,
        min_samples: int = 4_800,  # bỏ đoạn < 0.3 s
    ) -> None:
        self.max_samples = int(SAMPLE_RATE * max_utterance_s)
        self.pre_roll_frames = pre_roll_frames
        self.min_samples = min_samples
        self._carry = np.empty(0, dtype=np.float32)  # phần dư chưa đủ 1 khung
        self._pre_roll: list[np.ndarray] = []
        self._frames: list[np.ndarray] = []
        self._speech = 0
        self._silence = 0
        self._noise_floor = 0.008

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
            self._carry = np.empty(0, dtype=np.float32)
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
        self._speech = 0
        self._silence = 0

    def _step(self, frame: np.ndarray) -> np.ndarray | None:
        rms = float(np.sqrt(np.mean(frame**2)))

        # Trạng thái nghỉ: theo dõi ồn nền, giữ vài khung pre-roll để không mất âm đầu
        if not self._frames:
            self._noise_floor = min(0.035, max(0.004, 0.93 * self._noise_floor + 0.07 * rms))
            if rms < max(0.014, self._noise_floor * 2.00):
                self._pre_roll.append(frame)
                if len(self._pre_roll) > self.pre_roll_frames:
                    self._pre_roll.pop(0)
                return None
            self._frames = [*self._pre_roll, frame]
            self._pre_roll = []
            self._speech, self._silence = 1, 0
            return None

        # Đang gom câu
        self._frames.append(frame)
        if rms >= max(0.009, self._noise_floor * 1.35):
            self._speech += 1
            self._silence = 0
        else:
            self._silence += 1

        total = len(self._frames) * FRAME_SAMPLES
        if self._speech >= 3 and self._silence >= 5:        # nói >= 300 ms rồi lặng 500 ms
            return self._emit_all()
        if self._speech >= 2 and self._silence >= 6:        # từ ngắn ("dạ", "vâng", "ok")
            return self._emit_all()
        if self._silence >= 8:                              # lặng 800 ms
            return self._emit_all() if self._speech >= 3 else self._drop()
        if total >= self.max_samples:                       # nói liền quá dài
            return self._split_at_dip()
        return None

    def _drop(self) -> None:
        self._reset()
        return None

    def _split_at_dip(self) -> np.ndarray | None:
        frames = self._frames
        lo, hi = max(1, len(frames) - 20), max(2, len(frames) - 3)
        cut = min(range(lo, hi), key=lambda i: float(np.mean(frames[i] ** 2)), default=len(frames))
        head, tail = frames[:cut], frames[cut:]
        self._frames = tail  # không gối đoạn đầu -> không lặp từ
        self._speech = len(tail)
        self._silence = 0
        audio = np.concatenate(head) if head else None
        if audio is None or len(audio) < self.min_samples:
            return None
        return audio
