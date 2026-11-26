"""
session_scope.py (core)
=========================
[CUSTOM] Gắn dữ liệu theo PHIÊN HỌC (session). Mỗi phiên có kho riêng cho câu hỏi,
câu trả lời, sự kiện slide; lớp này khác lớp kia không thấy dữ liệu của nhau.

`session` là `session_id` của Flask (UUID). Không truyền `session` -> phạm vi
mặc định "" (hành vi cũ, một phòng chung) — CHỈ dùng được khi AI_AUTH_MODE=off.
Ở chế độ enforce (mặc định), mọi route REST theo phòng (core/auth.require_room_access)
trả 422 nếu thiếu `?session=` hoặc `session` không phải UUID; /room và /student cũ
không có session sẽ không tải được dữ liệu phòng.

Kiểm tra quyền (token Flask + thành viên phiên) cho REST nằm ở core/auth.py;
WebSocket chưa kiểm tra (vẫn nhận phạm vi mặc định) — xem README của ai-service.
"""

from __future__ import annotations

import re
import uuid
from collections import OrderedDict
from typing import Callable, Generic, TypeVar

from fastapi import HTTPException, Query

DEFAULT_SCOPE = ""
MAX_SESSIONS = 200  # chặn bộ nhớ phình khi có người gửi session_id bừa

_SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_HEX32_RE = re.compile(r"^[0-9a-fA-F]{32}$")

T = TypeVar("T")


def normalize_session(raw: str | None) -> str | None:
    """Trả về session hợp lệ (chuẩn hóa UUID về chữ thường có dấu gạch),
    DEFAULT_SCOPE nếu không truyền, None nếu sai định dạng."""
    if raw is None or raw == "":
        return DEFAULT_SCOPE
    cleaned = raw.strip()
    if not _SESSION_RE.fullmatch(cleaned):
        return None
    if "-" in cleaned or _HEX32_RE.fullmatch(cleaned):
        try:
            return str(uuid.UUID(cleaned))
        except (ValueError, TypeError, AttributeError):
            pass
    return cleaned


def session_param(session: str | None = Query(None, description="session_id của phiên học")) -> str:
    """Dependency cho REST: 422 nếu session sai định dạng."""
    normalized = normalize_session(session)
    if normalized is None:
        raise HTTPException(status_code=422, detail="Invalid session id")
    return normalized


class SessionScoped(Generic[T]):
    """Tạo (lười) và giữ một đối tượng riêng cho mỗi session. Giữ tối đa MAX_SESSIONS
    phiên gần nhất; phạm vi mặc định không bao giờ bị loại."""

    def __init__(
        self,
        factory: Callable[..., T],
        max_sessions: int = MAX_SESSIONS,
        *,
        pass_session: bool = False,
    ) -> None:
        self._factory = factory
        self._max = max_sessions
        self._pass_session = pass_session
        self._items: "OrderedDict[str, T]" = OrderedDict()

    def get(self, session: str = DEFAULT_SCOPE) -> T:
        norm = normalize_session(session)
        key = norm if norm is not None else session
        item = self._items.get(key)
        if item is None:
            item = self._factory(key) if self._pass_session else self._factory()
            self._items[key] = item
            self._evict()
        else:
            self._items.move_to_end(key)
        return item

    def _evict(self) -> None:
        while len(self._items) > self._max:
            victim = next((k for k in self._items if k != DEFAULT_SCOPE), None)
            if victim is None:
                break
            del self._items[victim]

    def __len__(self) -> int:
        return len(self._items)
