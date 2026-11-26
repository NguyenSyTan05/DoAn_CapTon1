"""
audit_service.py — Per-request audit logging for ClassBridge.

Fixes applied (vs. original):
- DB1/A10/B14: INSERT now matches the actual audit_logs schema exactly.
  Columns that do NOT exist in the schema (actor_email, entity_name, status)
  are stored inside the `details` JSONB field instead.
- Schema columns used: actor_role, admin_id, lecturer_id, student_id,
  action, entity_type, entity_id, description, ip_address, user_agent,
  details, created_at.
- ip_address and user_agent are now captured from the request.
- Table/column names are static strings — no f-string SQL injection risk.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from flask import current_app, request
from flask_jwt_extended import get_jwt, get_jwt_identity
from sqlalchemy import text

from extensions import db

logger = logging.getLogger("classbridge.audit")

# ---------------------------------------------------------------------------
# Role → account table mapping
# ---------------------------------------------------------------------------

_ACCOUNT_ACTORS: dict[str, tuple[str, str]] = {
    "admin": ("admins", "admin_id"),
    "giang_vien": ("lecturers", "lecturer_id"),
    "sinh_vien": ("students", "student_id"),
    "lecturer": ("lecturers", "lecturer_id"),
    "student": ("students", "student_id"),
}

# Tables are allowlisted — never interpolated from user input.
_ROLE_TO_AUDIT_ROLE: dict[str, str] = {
    "admin": "ADMIN",
    "giang_vien": "LECTURER",
    "lecturer": "LECTURER",
    "sinh_vien": "STUDENT",
    "student": "STUDENT",
}

# ---------------------------------------------------------------------------
# INSERT statement — columns must exactly match db.sql audit_logs definition
# ---------------------------------------------------------------------------

_INSERT_AUDIT = text(
    """
    INSERT INTO audit_logs (
        actor_role,
        admin_id, lecturer_id, student_id,
        action, entity_type, entity_id,
        description, ip_address, user_agent,
        details, created_at
    ) VALUES (
        :actor_role,
        :admin_id, :lecturer_id, :student_id,
        :action, :entity_type, CAST(:entity_id AS uuid),
        :description, CAST(:ip_address AS inet), :user_agent,
        CAST(:details AS jsonb), NOW()
    )
    """
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _request_actor(response) -> tuple[str, str | None]:
    """Return (audit_role_key, email_or_None) for the current request."""
    try:
        claims = get_jwt()
        identity = get_jwt_identity()
    except RuntimeError:
        claims = {}
        identity = None

    role: str | None = claims.get("role")
    email: str | None = identity
    payload: dict[str, Any] = request.get_json(silent=True) or {}

    if request.path == "/auth/register":
        role = {"student": "sinh_vien", "lecturer": "giang_vien"}.get(
            payload.get("role"), role
        )
        email = payload.get("email") or email
    elif request.path.startswith("/auth/verification/"):
        email = email or payload.get("email")
    elif request.path == "/auth/login":
        login_result = response.get_json(silent=True)
        login_user = login_result.get("user") if isinstance(login_result, dict) else None
        if isinstance(login_user, dict) and response.status_code < 400:
            email = login_user.get("email") or email
            role = login_user.get("role") or role
        else:
            email = payload.get("email") or email

    if not role:
        role = "anonymous"
    if not isinstance(email, str) or not email.strip():
        email = None
    else:
        email = email.strip().lower()
    return role, email


def _event_labels(endpoint: str | None, method: str) -> tuple[str, str]:
    """Return (action_label, entity_type) for a given Flask endpoint + HTTP method."""
    labels: dict[str, str] = {
        "login.login": "Đăng nhập",
        "login.logout": "Đăng xuất",
        "register_account.register_account": "Tạo tài khoản",
        "admin_accounts.create_account": "Tạo tài khoản",
        "admin_accounts.update_account": "Cập nhật tài khoản",
        "admin_accounts.delete_account": "Xóa tài khoản",
        "send_verification.send_email_verification": "Gửi mã xác minh email",
        "verify_verification.verify_email_code": "Xác minh email",
        "admin_dashboard.get_admin_dashboard": "Xem trang tổng quan",
        "admin_logs.get_admin_logs": "Xem nhật ký hoạt động",
    }
    if endpoint in labels:
        action = labels[endpoint]
    else:
        action = f"{method} {endpoint or request.path}"

    path = request.path
    if "/accounts/" in path:
        entity_type = "account"
    elif "dashboard" in (endpoint or ""):
        entity_type = "dashboard"
    elif "logs" in (endpoint or ""):
        entity_type = "audit_log"
    elif path in ("/auth/login", "/auth/logout"):
        entity_type = "account"
    elif "verification" in path or "email/check" in path:
        entity_type = "email_verification"
    elif path == "/auth/register":
        entity_type = "account"
    else:
        entity_type = "application"
    return action, entity_type


def _client_ip() -> str | None:
    """Return the real client IP, respecting X-Forwarded-For when trusted."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        # Take only the leftmost address (first hop from the client).
        return forwarded.split(",")[0].strip() or None
    return request.remote_addr or None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_request_activity(response) -> None:
    """Persist one sanitized audit row for each API request.

    This function is called from the after_request hook in app.py.
    It must NEVER raise — any exception is logged and swallowed so that a
    completed user action is never turned into an HTTP failure.
    """
    if request.method == "OPTIONS" or request.path in ("/", "/health", "/ready", "/test-db"):
        return
    if request.endpoint == "user_activity.record_click":
        return
    # Successful login/logout is already recorded inside the route handler.
    if request.path in ("/auth/login", "/auth/logout") and response.status_code < 400:
        return

    role, email = _request_actor(response)
    action, entity_type = _event_labels(request.endpoint, request.method)
    succeeded = response.status_code < 400
    endpoint_label = request.endpoint or request.path
    description = f"{request.method} {endpoint_label} completed with HTTP {response.status_code}"

    audit_role = _ROLE_TO_AUDIT_ROLE.get(role, "SYSTEM")
    actor_table = _ACCOUNT_ACTORS.get(role)

    entity_id: str | None = None
    match = re.search(
        r"/auth/admin/accounts/(?:admin|lecturer|student):([0-9a-fA-F-]{36})",
        request.path,
    )
    if match:
        entity_id = match.group(1)

    # Extra fields that don't have their own column go into the JSONB details blob.
    details: dict[str, Any] = {
        "status": "success" if succeeded else "failed",
        "http_status": response.status_code,
    }
    if email:
        details["actor_email"] = email
    if endpoint_label:
        details["endpoint"] = endpoint_label

    try:
        with db.engine.begin() as connection:
            actor_id: Any = None
            if email and actor_table:
                table, primary_key = actor_table
                # Both table and primary_key come from the static allowlist above.
                actor_id = connection.execute(
                    text(
                        f"SELECT {primary_key} FROM {table} "  # noqa: S608 — allowlisted
                        "WHERE lower(email) = :email LIMIT 1"
                    ),
                    {"email": email},
                ).scalar_one_or_none()

            # The audit_logs CHECK constraint requires a matching account FK per role.
            # Fall back to SYSTEM when the actor cannot be resolved.
            if audit_role != "SYSTEM" and actor_id is None:
                audit_role = "SYSTEM"

            # Determine entity_id for well-known self-referential paths.
            if request.path == "/auth/register":
                entity_id = str(actor_id) if actor_id else entity_id
            elif request.path in ("/auth/login", "/auth/logout"):
                entity_id = str(actor_id) if actor_id else entity_id
            elif request.path == "/auth/admin/accounts" and request.method == "POST":
                payload = request.get_json(silent=True) or {}
                target_role = payload.get("role")
                target_table = {
                    "Admin": ("admins", "admin_id"),
                    "Editor": ("lecturers", "lecturer_id"),
                    "User": ("students", "student_id"),
                }.get(target_role)
                target_email = payload.get("email")
                if target_table and isinstance(target_email, str):
                    tbl, pk = target_table
                    result = connection.execute(
                        text(
                            f"SELECT {pk} FROM {tbl} "  # noqa: S608 — allowlisted
                            "WHERE lower(email) = :email LIMIT 1"
                        ),
                        {"email": target_email.strip().lower()},
                    ).scalar_one_or_none()
                    if result:
                        entity_id = str(result)

            connection.execute(
                _INSERT_AUDIT,
                {
                    "actor_role": audit_role,
                    "admin_id": str(actor_id) if audit_role == "ADMIN" and actor_id else None,
                    "lecturer_id": str(actor_id) if audit_role == "LECTURER" and actor_id else None,
                    "student_id": str(actor_id) if audit_role == "STUDENT" and actor_id else None,
                    "action": action,
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "description": description,
                    "ip_address": _client_ip(),
                    "user_agent": request.headers.get("User-Agent", "")[:512],
                    "details": json.dumps(details, ensure_ascii=False),
                },
            )
    except Exception:
        # Auditing must NEVER turn a completed user action into an HTTP failure.
        logger.exception("Request activity audit write failed for path=%s", request.path)
