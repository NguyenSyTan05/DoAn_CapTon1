"""
session_scope.py (core)
=========================
[CUSTOM] Gắn dữ liệu theo PHIÊN HỌC (session). Mỗi phiên có kho riêng cho câu hỏi,
câu trả lời, sự kiện slide; lớp này khác lớp kia không thấy dữ liệu của nhau.

`session` là `session_id` của Flask (UUID). Không truyền `session` -> dùng phạm vi
mặc định "" (hành vi cũ, một phòng chung) để /room và /student cũ vẫn chạy.

Chưa có xác thực: ai biết session_id đều đọc/ghi được phòng đó. Việc kiểm tra quyền
(token Flask) là bước riêng — xem README của ai-service.
"""

from __future__ import annotations

import re
from collections import OrderedDict
from typing import Callable, Generic, TypeVar

from fastapi import HTTPException, Query

DEFAULT_SCOPE = ""
MAX_SESSIONS = 200  # chặn bộ nhớ phình khi có người gửi session_id bừa

_SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

T = TypeVar("T")


def normalize_session(raw: str | None) -> str | None:
    """Trả về session hợp lệ, DEFAULT_SCOPE nếu không truyền, None nếu sai định dạng."""
    if raw is None or raw == "":
        return DEFAULT_SCOPE
    return raw if _SESSION_RE.fullmatch(raw) else None


def session_param(session: str | None = Query(None, description="session_id của phiên học")) -> str:
    """Dependency cho REST: 422 nếu session sai định dạng."""
    normalized = normalize_session(session)
    if normalized is None:
        raise HTTPException(status_code=422, detail="Invalid session id")
    return normalized


class SessionScoped(Generic[T]):
    """Tạo (lười) và giữ một đối tượng riêng cho mỗi session. Giữ tối đa MAX_SESSIONS
    phiên gần nhất; phạm vi mặc định không bao giờ bị loại."""

    def __init__(self, factory: Callable[[], T], max_sessions: int = MAX_SESSIONS) -> None:
        self._factory = factory
        self._max = max_sessions
        self._items: "OrderedDict[str, T]" = OrderedDict()

    def get(self, session: str = DEFAULT_SCOPE) -> T:
        item = self._items.get(session)
        if item is None:
            item = self._factory()
            self._items[session] = item
            self._evict()
        else:
            self._items.move_to_end(session)
        return item

    def _evict(self) -> None:
        while len(self._items) > self._max:
            victim = next((k for k in self._items if k != DEFAULT_SCOPE), None)
            if victim is None:
                break
            del self._items[victim]

    def __len__(self) -> int:
        return len(self._items)
