"""
auth.py (core)
===============
[CUSTOM] Xác thực cho REST của ai-service (giai đoạn 1: chỉ REST, WebSocket chưa đổi).

1. Kiểm JWT của Flask ngay tại đây (PyJWT, HS256, cùng SECRET_KEY với Flask):
   bắt buộc `exp`, `type == "access"`, `role` thuộc admin | giang_vien | sinh_vien | student
   ("student" là giá trị cũ Flask vẫn chấp nhận). Sai -> 401.
2. Quyền vào phòng: hỏi Flask MỘT lần cho mỗi (token, phiên)
   `GET {FLASK_API_URL}/auth/sessions/<session_id>/access` rồi nhớ kết quả trong RAM
   (TTL ngắn, giới hạn kích thước). Flask không trả lời được -> 503 (không bao giờ cho qua).
   `?session=` phải là UUID (sai -> 422, không hỏi Flask). 403 giữ nguyên `code` của Flask:
   session_forbidden | session_closed (phiên đã kết thúc/bị huỷ).

Biến môi trường:
  - SECRET_KEY     : trùng giá trị với Flask; >= 32 ký tự khi bật xác thực.
  - FLASK_API_URL  : mặc định http://127.0.0.1:5000
  - AI_AUTH_MODE   : "enforce" (mặc định) | "off" (bỏ qua mọi kiểm tra — chỉ dùng cho dev/test).

Dùng trong router:
    @router.get("/x", dependencies=[Depends(require_room_access(ANY_MEMBER))])
    @router.post("/y", dependencies=[Depends(require_user)])
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable, Iterable
from urllib.parse import quote

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

try:  # starlette mới dùng httpx2 (kế nhiệm httpx, cùng API); vẫn chạy được với httpx cũ
    import httpx2 as httpx
except ImportError:  # pragma: no cover
    import httpx  # type: ignore[no-redef]

from core.session_scope import DEFAULT_SCOPE, session_param

logger = logging.getLogger("classbridge.auth")

# "student": giá trị cũ, Flask vẫn chấp nhận (auth_utils.STUDENT_ROLES); quyền vào phòng vẫn do Flask quyết.
KNOWN_ROLES = frozenset({"admin", "giang_vien", "sinh_vien", "student"})
KNOWN_ACCESS = frozenset({"lecturer", "student", "admin"})

# Nhóm quyền theo phòng (giá trị `access` Flask trả về)
LECTURER_ONLY = frozenset({"lecturer"})
STUDENT_OR_LECTURER = frozenset({"lecturer", "student"})
ANY_MEMBER = KNOWN_ACCESS

MIN_SECRET_LEN = 32
FLASK_TIMEOUT_S = 3.0
CACHE_TTL_S = 300.0          # nhớ quyền 5 phút
NEGATIVE_CACHE_TTL_S = 30.0  # nhớ "bị từ chối / đã đóng / không có phiên" ngắn hơn
FORBIDDEN_CODES = frozenset({"session_forbidden", "session_closed"})
CACHE_MAX_ENTRIES = 2048


# =====================================================================
# Cấu hình
# =====================================================================

@dataclass
class AuthSettings:
    mode: str
    secret_key: str
    flask_api_url: str

    @property
    def enabled(self) -> bool:
        return self.mode != "off"


def load_settings() -> AuthSettings:
    return AuthSettings(
        mode=os.getenv("AI_AUTH_MODE", "enforce").strip().lower() or "enforce",
        secret_key=os.getenv("SECRET_KEY", ""),
        flask_api_url=os.getenv("FLASK_API_URL", "http://127.0.0.1:5000").strip().rstrip("/"),
    )


settings = load_settings()


def reload_settings() -> AuthSettings:
    """Đọc lại biến môi trường (dùng cho test) và xoá cache quyền."""
    global settings
    settings = load_settings()
    _access_cache.clear()
    return settings


def validate_settings() -> None:
    """Gọi lúc khởi động (core/lifespan.py). Cấu hình sai -> dừng hẳn, không chạy 'mở cửa'."""
    if settings.mode not in ("enforce", "off"):
        raise RuntimeError(f"AI_AUTH_MODE không hợp lệ: {settings.mode!r} (chỉ nhận 'enforce' hoặc 'off')")
    if not settings.enabled:
        logger.warning(
            "⚠️  AI_AUTH_MODE=off — ai-service KHÔNG kiểm tra JWT/quyền vào phòng. "
            "Chỉ dùng cho dev/test, không bao giờ dùng khi triển khai."
        )
        return
    if len(settings.secret_key) < MIN_SECRET_LEN:
        raise RuntimeError(
            f"SECRET_KEY phải có ít nhất {MIN_SECRET_LEN} ký tự (trùng với Flask) khi AI_AUTH_MODE=enforce"
        )
    logger.info("Xác thực bật (enforce): kiểm JWT cục bộ, hỏi quyền phòng tại %s", settings.flask_api_url)


# =====================================================================
# Kiểm token
# =====================================================================

@dataclass(frozen=True)
class AuthUser:
    sub: str
    role: str
    jti: str | None
    exp: float
    token: str


_DEV_USER = AuthUser(sub="dev", role="admin", jti=None, exp=float("inf"), token="")

_bearer = HTTPBearer(auto_error=False)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status_code=401, detail=detail, headers={"WWW-Authenticate": "Bearer"})


def verify_token(token: str) -> AuthUser:
    try:
        claims = jwt.decode(
            token,
            settings.secret_key,
            algorithms=["HS256"],
            options={"require": ["exp", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise _unauthorized("Token expired") from exc
    except jwt.PyJWTError as exc:
        raise _unauthorized("Invalid token") from exc

    if claims.get("type") != "access":
        raise _unauthorized("Invalid token type")
    role = claims.get("role")
    if role not in KNOWN_ROLES:
        raise _unauthorized("Invalid role")
    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub:
        raise _unauthorized("Invalid subject")
    jti = claims.get("jti")
    return AuthUser(
        sub=sub,
        role=role,
        jti=jti if isinstance(jti, str) and jti else None,
        exp=float(claims["exp"]),
        token=token,
    )


async def require_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthUser:
    """Dependency: bất kỳ token Flask hợp lệ nào (không kiểm phòng)."""
    if not settings.enabled:
        return _DEV_USER
    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise _unauthorized("Missing bearer token")
    return verify_token(credentials.credentials)


# =====================================================================
# Quyền vào phòng (hỏi Flask, có cache)
# =====================================================================

@dataclass(frozen=True)
class RoomAccess:
    user: AuthUser
    session: str
    access: str  # lecturer | student | admin


class _AccessCache:
    """LRU có hạn dùng. Giá trị: (hết hạn lúc, access hoặc HTTPException đã cache)."""

    def __init__(self, max_entries: int = CACHE_MAX_ENTRIES) -> None:
        self._max = max_entries
        self._items: "OrderedDict[tuple[str, str], tuple[float, str | HTTPException]]" = OrderedDict()

    def get(self, key: tuple[str, str]) -> str | HTTPException | None:
        hit = self._items.get(key)
        if hit is None:
            return None
        expires_at, value = hit
        if expires_at <= time.monotonic():
            del self._items[key]
            return None
        self._items.move_to_end(key)
        return value

    def put(self, key: tuple[str, str], value: str | HTTPException, ttl: float) -> None:
        if ttl <= 0:
            return
        self._items[key] = (time.monotonic() + ttl, value)
        self._items.move_to_end(key)
        while len(self._items) > self._max:
            self._items.popitem(last=False)

    def clear(self) -> None:
        self._items.clear()

    def __len__(self) -> int:
        return len(self._items)


_access_cache = _AccessCache()


def _cache_key(user: AuthUser, session: str) -> tuple[str, str]:
    return (f"jti:{user.jti}" if user.jti else f"sub:{user.sub}", session)


def _code(response) -> str | None:
    try:
        body = response.json()
    except ValueError:
        return None
    return body.get("code") if isinstance(body, dict) else None


async def fetch_room_access(user: AuthUser, session: str) -> str:
    """Hỏi Flask quyền của `user` trong `session`. Trả về lecturer|student|admin hoặc ném HTTPException."""
    url = f"{settings.flask_api_url}/auth/sessions/{quote(session, safe='')}/access"
    try:
        async with httpx.AsyncClient(timeout=FLASK_TIMEOUT_S) as client:
            response = await client.get(url, headers={"Authorization": f"Bearer {user.token}"})
    except httpx.HTTPError as exc:
        logger.warning("Không hỏi được quyền phòng từ Flask (%s): %s", url, exc)
        raise HTTPException(status_code=503, detail="Auth service unavailable") from exc

    status = response.status_code
    if status == 200:
        try:
            access = response.json().get("access")
        except (ValueError, AttributeError):
            access = None
        if access not in KNOWN_ACCESS:
            logger.error("Flask trả access không hợp lệ cho phiên %s: %r", session, access)
            raise HTTPException(status_code=503, detail="Auth service returned an invalid response")
        return access
    if status == 401:
        raise _unauthorized("Invalid token")
    if status == 400:
        # Flask: invalid_session_id — lỗi của client, không phải sự cố (bình thường đã chặn trước khi gọi).
        raise HTTPException(status_code=422, detail="Invalid session id")
    if status == 403:
        code = _code(response)
        raise HTTPException(
            status_code=403, detail={"code": code if code in FORBIDDEN_CODES else "session_forbidden"}
        )
    if status == 404:
        raise HTTPException(status_code=404, detail={"code": _code(response) or "session_not_found"})
    logger.warning("Flask trả mã %s khi hỏi quyền phòng %s", status, session)
    raise HTTPException(status_code=503, detail="Auth service unavailable")


async def get_room_access(user: AuthUser, session: str) -> str:
    key = _cache_key(user, session)
    cached = _access_cache.get(key)
    if isinstance(cached, HTTPException):
        raise HTTPException(status_code=cached.status_code, detail=cached.detail)
    if cached is not None:
        return cached

    token_left = user.exp - time.time()  # không nhớ lâu hơn hạn của token
    try:
        access = await fetch_room_access(user, session)
    except HTTPException as exc:
        if exc.status_code in (403, 404):
            _access_cache.put(key, exc, min(NEGATIVE_CACHE_TTL_S, token_left))
        raise
    _access_cache.put(key, access, min(CACHE_TTL_S, token_left))
    return access


def is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except (ValueError, TypeError, AttributeError):
        return False
    return True


def require_room_access(allowed: Iterable[str] = ANY_MEMBER) -> Callable:
    """Dependency factory: token hợp lệ + là thành viên phiên (`?session=`) với quyền thuộc `allowed`.

    Ở chế độ enforce, thiếu `?session=` (phạm vi mặc định "") hoặc session không phải UUID -> 422
    (không hỏi Flask). Chế độ off giữ quy tắc cũ của session_param ([A-Za-z0-9_-])."""
    allowed_set = frozenset(allowed)
    unknown = allowed_set - KNOWN_ACCESS
    if unknown:
        raise ValueError(f"Unknown access values: {sorted(unknown)}")

    async def dependency(
        session: str = Depends(session_param),
        credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    ) -> RoomAccess:
        if not settings.enabled:
            return RoomAccess(user=_DEV_USER, session=session, access="admin")
        user = await require_user(credentials)
        if session == DEFAULT_SCOPE:
            raise HTTPException(status_code=422, detail="session is required")
        if not is_uuid(session):
            raise HTTPException(status_code=422, detail="Invalid session id")
        access = await get_room_access(user, session)
        if access not in allowed_set:
            raise HTTPException(status_code=403, detail={"code": "role_forbidden"})
        return RoomAccess(user=user, session=session, access=access)

    return dependency
