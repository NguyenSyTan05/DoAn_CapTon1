"""
pii_masker.py (core)
=====================
Lớp bảo vệ tính ẩn danh tuyệt đối cho câu hỏi của sinh viên:
Tự động phát hiện và che (redact) thông tin định danh cá nhân (PII) gồm:
- Địa chỉ Email -> `[EMAIL ẨN DANH]`
- Mã số sinh viên 11 chữ số -> `[MSSV ẨN DANH]`
- Số điện thoại di động Việt Nam / quốc tế -> `[SĐT ẨN DANH]`
"""

from __future__ import annotations

import re

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_STUDENT_ID_RE = re.compile(r"\b\d{11}\b")
_VN_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?84[\s.-]?|0)(?:3|5|7|8|9)(?:[\s.-]?\d){8}(?!\d)"
)


def mask_pii(text: str) -> tuple[str, int]:
    """Trả về `(văn_bản_đã_che_PII, tổng_số_vị_trí_đã_che)`."""
    if not text:
        return text, 0

    total = 0
    masked, n_email = _EMAIL_RE.subn("[EMAIL ẨN DANH]", text)
    total += n_email

    masked, n_sid = _STUDENT_ID_RE.subn("[MSSV ẨN DANH]", masked)
    total += n_sid

    masked, n_phone = _VN_PHONE_RE.subn("[SĐT ẨN DANH]", masked)
    total += n_phone

    return masked, total
