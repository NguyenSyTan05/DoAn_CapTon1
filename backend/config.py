"""
config.py — ClassBridge Flask configuration.

Fixes applied (vs. original):
- A13: DATABASE_URL is validated at import time; None → RuntimeError with actionable message.
- S4:  ALLOW_LAN_ORIGINS default changed to '0' (opt-in, not opt-out).
- Remaining logic unchanged.
"""

from __future__ import annotations

import math
import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
load_dotenv(BACKEND_DIR / ".env")
load_dotenv(BACKEND_DIR / "routes" / ".env")
email_config_path = BACKEND_DIR / ".env.email"
if not email_config_path.exists():
    email_config_path = BACKEND_DIR / "routes" / ".env.email"
load_dotenv(email_config_path, override=True)


MIN_SECRET_KEY_LENGTH = 32


def _require_secret_key() -> str:
    value = os.getenv("SECRET_KEY")
    if not value or len(value) < MIN_SECRET_KEY_LENGTH:
        raise RuntimeError(
            "Thiếu hoặc SECRET_KEY quá ngắn: biến môi trường SECRET_KEY là bắt buộc "
            f"và phải dài ít nhất {MIN_SECRET_KEY_LENGTH} ký tự. "
            "Hãy đặt một chuỗi ngẫu nhiên dài trong backend/.env, ví dụ tạo bằng: "
            'python -c "import secrets; print(secrets.token_urlsafe(48))"'
        )
    return value


def _require_database_url() -> str:
    """Fail fast at startup if DATABASE_URL is absent (A13)."""
    value = os.getenv("DATABASE_URL")
    if not value or not value.strip():
        raise RuntimeError(
            "DATABASE_URL is not set. "
            "Add DATABASE_URL=postgresql://user:pass@host:5432/classbridge "
            "to backend/.env before starting the server."
        )
    return value.strip()


def _token_hours(name: str, default: float) -> float:
    """Return JWT lifetime in hours for the given role; must be a positive number."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return float(default)
    try:
        value = float(raw)
    except ValueError:
        value = 0.0
    if not (math.isfinite(value) and value > 0):
        raise RuntimeError(
            f"{name} phải là số giờ dương (ví dụ 1, 4, 8), nhận được: {raw!r}"
        )
    return value


class Config:
    # A13: Validated at class-definition time — missing value raises immediately.
    SQLALCHEMY_DATABASE_URI: str = _require_database_url()
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False

    SECRET_KEY: str = _require_secret_key()

    FRONTEND_ORIGIN: str = os.getenv("FRONTEND_ORIGIN", "http://localhost:4000")

    # S4: Default is now '0' — LAN origins are opt-in, not opt-out.
    ALLOW_LAN_ORIGINS: bool = (
        os.getenv("ALLOW_LAN_ORIGINS", "0").strip().lower() in ("1", "true", "yes")
    )

    SMTP_HOST: str | None = os.getenv("SMTP_HOST")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USERNAME: str | None = os.getenv("SMTP_USERNAME")
    SMTP_PASSWORD: str | None = os.getenv("SMTP_PASSWORD")
    SMTP_FROM: str | None = os.getenv("SMTP_FROM")
    SMTP_USE_TLS: bool = os.getenv("SMTP_USE_TLS", "true").lower() == "true"

    EMAIL_VALIDATION_API_KEY: str | None = os.getenv("EMAIL_VALIDATION_API_KEY")

    # JWT lifetime per role (hours). All roles share the same SECRET_KEY.
    ADMIN_TOKEN_HOURS: float = _token_hours("ADMIN_TOKEN_HOURS", 1)
    LECTURER_TOKEN_HOURS: float = _token_hours("LECTURER_TOKEN_HOURS", 8)
    STUDENT_TOKEN_HOURS: float = _token_hours("STUDENT_TOKEN_HOURS", 4)
