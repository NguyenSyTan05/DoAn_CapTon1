"""
guardrails.py (core)
=====================
Hàng rào phòng thủ chống tấn công tiêm lệnh (Prompt Injection) và làm sạch
ngữ cảnh không tin cậy trước khi đưa vào mô hình tổng hợp (Summarizer / RAG).
"""

from __future__ import annotations

import re

_INJECTION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"\b(ignore|disregard|forget|bypass)\s+(all\s+|any\s+)?(previous|prior|above|system)\s+(instructions?|prompts?|rules?)\b",
            re.IGNORECASE,
        ),
        "Phát hiện mẫu câu cố tình ghi đè chỉ dẫn hệ thống (Prompt Injection).",
    ),
    (
        re.compile(
            r"(bỏ\s+qua|phớt\s+lờ|xóa\s+bỏ)\s+(mọi\s+|tất\s+cả\s+)?(chỉ\s+dẫn|hướng\s+dẫn|quy\s+tắc|lệnh)\s+(trước|hệ\s+thống)",
            re.IGNORECASE,
        ),
        "Phát hiện câu lệnh cố tình bỏ qua quy tắc hệ thống.",
    ),
    (
        re.compile(
            r"\b(reveal|print|show|output|leak|dump)\s+(your\s+|the\s+)?(system\s+prompt|hidden\s+prompt|secret\s+key|api\s+key|env)\b",
            re.IGNORECASE,
        ),
        "Phát hiện yêu cầu trích xuất trái phép cấu hình hoặc prompt hệ thống.",
    ),
    (
        re.compile(
            r"(tiết\s+lộ|in\s+ra|hiển\s+thị)\s+(system\s+prompt|prompt\s+hệ\s+thống|khóa\s+bí\s+mật|mật\s+khẩu\s+hệ\s+thống)",
            re.IGNORECASE,
        ),
        "Phát hiện yêu cầu tiết lộ thông tin nội bộ hệ thống.",
    ),
    (
        re.compile(
            r"(<\|im_start\|>|<\|im_end\|>|<\|system\|>|\[INST\]|\[/INST\]|<<SYS>>|<</SYS>>)",
            re.IGNORECASE,
        ),
        "Phát hiện thẻ điều khiển đặc biệt giả mạo vai trò mô hình.",
    ),
    (
        re.compile(
            r"\b(you\s+are\s+now\s+DAN|do\s+anything\s+now|developer\s+mode\s+enabled|jailbreak)\b",
            re.IGNORECASE,
        ),
        "Phát hiện mẫu tấn công vượt rào (Jailbreak).",
    ),
)


def inspect_prompt_injection(text: str) -> str | None:
    """Trả về thông báo chặn tiếng Việt nếu phát hiện tấn công tiêm lệnh, ngược lại `None`."""
    if not text or not text.strip():
        return None
    compact = re.sub(r"\s+", " ", text.strip())
    for pattern, reason in _INJECTION_PATTERNS:
        if pattern.search(compact):
            return reason
    return None


def sanitize_untrusted_context(text: str) -> str:
    """Làm sạch chuỗi ngữ cảnh trước khi ghép vào prompt của LLM ngoài."""
    if not text:
        return ""
    cleaned = text
    for pattern, _ in _INJECTION_PATTERNS:
        cleaned = pattern.sub("[NỘI DUNG ĐÃ LỌC]", cleaned)
    return cleaned
