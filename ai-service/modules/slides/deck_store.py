"""
deck_store.py (modules/slides)
================================
Bộ slide (PDF) mà giảng viên chia sẻ trong MỘT phiên học: file PDF, tên file,
phiên bản (tăng mỗi lần upload lại), số trang hiện tại và văn bản trích xuất
từng trang (`slide_texts`) phục vụ Tóm tắt bài giảng AI & Chatbot Hỏi đáp RAG.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from modules.slides.pdf_extractor import extract_pdf_pages_text

MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_DECKS = 10


@dataclass
class SlideDeck:
    content: bytes = b""
    filename: str = ""
    version: int = 0
    page: int = 1
    slide_texts: dict[int, str] = field(default_factory=dict)

    @property
    def has_file(self) -> bool:
        return bool(self.content)

    def set_file(self, content: bytes, filename: str) -> None:
        self.content = content
        self.filename = filename
        self.version += 1
        self.page = 1
        self.slide_texts = extract_pdf_pages_text(content)

    def set_page(self, page: int) -> None:
        self.page = max(1, page)

    def state(self) -> dict:
        return {
            "type": "state",
            "has_file": self.has_file,
            "filename": self.filename,
            "version": self.version,
            "page": self.page,
            "extracted_pages": len(self.slide_texts),
        }
