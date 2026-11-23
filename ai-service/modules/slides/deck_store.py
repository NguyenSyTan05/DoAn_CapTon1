"""
deck_store.py (modules/slides)
================================
[CUSTOM] Bộ slide (PDF) mà giảng viên chia sẻ trong MỘT phiên học: file PDF, tên file,
phiên bản (tăng mỗi lần upload lại) và số trang hiện tại. Sinh viên tải file về và theo
số trang qua WebSocket /api/v1/ws/slides.

In-memory như các store khác (mất khi khởi động lại). Mỗi phiên tối đa MAX_PDF_BYTES và
chỉ giữ MAX_DECKS bộ gần nhất (xem lifespan) để không phình bộ nhớ.
"""

from __future__ import annotations

from dataclasses import dataclass

MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_DECKS = 10


@dataclass
class SlideDeck:
    content: bytes = b""
    filename: str = ""
    version: int = 0
    page: int = 1

    @property
    def has_file(self) -> bool:
        return bool(self.content)

    def set_file(self, content: bytes, filename: str) -> None:
        self.content = content
        self.filename = filename
        self.version += 1
        self.page = 1

    def set_page(self, page: int) -> None:
        self.page = max(1, page)

    def state(self) -> dict:
        return {
            "type": "state",
            "has_file": self.has_file,
            "filename": self.filename,
            "version": self.version,
            "page": self.page,
        }
