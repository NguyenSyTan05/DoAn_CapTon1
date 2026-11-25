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


def _require_secret_key():
    value = os.getenv("SECRET_KEY")
    if not value or len(value) < MIN_SECRET_KEY_LENGTH:
        raise RuntimeError(
            "Thiếu hoặc SECRET_KEY quá ngắn: biến môi trường SECRET_KEY là bắt buộc "
            f"và phải dài ít nhất {MIN_SECRET_KEY_LENGTH} ký tự. "
            "Hãy đặt một chuỗi ngẫu nhiên dài trong backend/.env, ví dụ tạo bằng: "
            'python -c "import secrets; print(secrets.token_urlsafe(48))"'
        )
    return value


def _token_hours(name, default):
    """Số giờ sống của JWT theo vai trò; phải là số dương."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return float(default)
    try:
        value = float(raw)
    except ValueError:
        value = 0.0
    if not (math.isfinite(value) and value > 0):
        raise RuntimeError(f"{name} phải là số giờ dương (ví dụ 1, 4, 8), nhận được: {raw!r}")
    return value


class Config:
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = _require_secret_key()
    FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
    SMTP_HOST = os.getenv("SMTP_HOST")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USERNAME = os.getenv("SMTP_USERNAME")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
    SMTP_FROM = os.getenv("SMTP_FROM")
    SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
    EMAIL_VALIDATION_API_KEY = os.getenv("EMAIL_VALIDATION_API_KEY")
    # Thời hạn access token theo vai trò (giờ). Cùng một SECRET_KEY ký cho mọi vai trò.
    ADMIN_TOKEN_HOURS = _token_hours("ADMIN_TOKEN_HOURS", 1)
    LECTURER_TOKEN_HOURS = _token_hours("LECTURER_TOKEN_HOURS", 8)
    STUDENT_TOKEN_HOURS = _token_hours("STUDENT_TOKEN_HOURS", 4)
