"""
slide_store.py
================
[CUSTOM INTERFACE] Server-side storage for slide-navigation events — same
swappable pattern as answer_store.py / question_store.py.

Purpose: correlate WHEN each slide was shown with WHEN questions were
asked, to compute "which slide generated the most questions" (the
engagement-per-slide diagram). Slide-change detection itself is a plain,
deterministic UI event (teacher clicked Next/Prev in the built-in PDF
viewer) — no computer vision, no AI needed for this part, since the
lecturer uploads slides directly (see SlideViewer.tsx) rather than relying
on screen-share scene-change detection.

InMemorySlideEventStore is the only implementation today — same
"no database yet" caveat as the other *_store.py files.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class SlideEventRecord:
    slide_number: int
    started_at: str  # ISO-8601, set by the caller (main.py)


class SlideEventStore(ABC):
    @abstractmethod
    def list_all(self) -> list[SlideEventRecord]:
        """Return every recorded slide-change event, oldest first."""
        raise NotImplementedError

    @abstractmethod
    def add(self, record: SlideEventRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    def clear(self) -> None:
        """Remove every recorded event — e.g. starting a fresh session."""
        raise NotImplementedError


class InMemorySlideEventStore(SlideEventStore):
    def __init__(self) -> None:
        self._events: list[SlideEventRecord] = []

    def list_all(self) -> list[SlideEventRecord]:
        return sorted(self._events, key=lambda r: r.started_at)

    def add(self, record: SlideEventRecord) -> None:
        self._events.append(record)

    def clear(self) -> None:
        self._events.clear()


def compute_engagement(
    slide_events: list[SlideEventRecord], question_timestamps: list[str]
) -> list[dict]:
    """Với mỗi câu hỏi, tìm slide đang hiển thị tại đúng thời điểm câu hỏi
    được gửi (sự kiện chuyển slide gần nhất TRƯỚC timestamp câu hỏi), rồi
    đếm số câu hỏi theo từng slide_number.

    [CUSTOM — thuần tính toán, không dùng AI] Đây là code phụ trợ
    (sort + bucket), không thuộc phạm vi module NCKH (clustering) — không
    cần thuật toán học máy nào cho việc đối chiếu timestamp đơn giản này.
    Giả định các timestamp là chuỗi ISO-8601 cùng định dạng, so sánh trực
    tiếp bằng chuỗi vẫn đúng thứ tự thời gian."""
    sorted_events = sorted(slide_events, key=lambda r: r.started_at)
    counts: dict[int, int] = {}

    for q_ts in question_timestamps:
        current_slide: int | None = None
        for event in sorted_events:
            if event.started_at <= q_ts:
                current_slide = event.slide_number
            else:
                break
        if current_slide is not None:
            counts[current_slide] = counts.get(current_slide, 0) + 1

    return [
        {"slide_number": slide, "question_count": count}
        for slide, count in sorted(counts.items())
    ]
