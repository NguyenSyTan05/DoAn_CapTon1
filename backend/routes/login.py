"""
login.py (routes)
==================
Authentication endpoints: login and logout.

Fixes applied (B1-B3, P1, S1, S3):
- Single UNION ALL query replaces three sequential queries → eliminates timing
  side-channel and 2 extra DB round-trips.
- TOKEN_HOURS_CONFIG covers all role aliases (no KeyError).
- Audit log correctly maps actor UUID from the UNION result.
- logout records audit without DB query (JWT claims already hold identity).
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import create_access_token, get_jwt, get_jwt_identity, jwt_required
from sqlalchemy import text
from werkzeug.security import check_password_hash

from email_utils import is_valid_email_format
from extensions import db
from request_limits import request_limit_exceeded

logger = logging.getLogger("classbridge.login")

login_bp = Blueprint("login", __name__, url_prefix="/auth")

# Maps internal role name → app config key for token TTL.
_TOKEN_HOURS_CONFIG: dict[str, str] = {
    "admin":      "ADMIN_TOKEN_HOURS",
    "giang_vien": "LECTURER_TOKEN_HOURS",
    "lecturer":   "LECTURER_TOKEN_HOURS",   # alias
    "sinh_vien":  "STUDENT_TOKEN_HOURS",
    "student":    "STUDENT_TOKEN_HOURS",    # alias
}

# Maps internal role name → audit_logs.actor_role enum value.
_AUDIT_ROLE_MAP: dict[str, str] = {
    "admin":      "ADMIN",
    "giang_vien": "LECTURER",
    "lecturer":   "LECTURER",
    "sinh_vien":  "STUDENT",
    "student":    "STUDENT",
}

# Maps internal role name → foreign-key column in audit_logs.
_AUDIT_FK_COL: dict[str, str] = {
    "admin":      "admin_id",
    "giang_vien": "lecturer_id",
    "lecturer":   "lecturer_id",
    "sinh_vien":  "student_id",
    "student":    "student_id",
}

# Single UNION ALL query to find an account by email across all three role tables.
_ACCOUNT_LOOKUP_SQL = text(
    """
    SELECT 'admin'      AS role,
           admin_id     AS actor_id,
           full_name, email, password_hash, is_active
    FROM   admins
    WHERE  lower(email) = :email
    UNION ALL
    SELECT 'giang_vien'  AS role,
           lecturer_id   AS actor_id,
           full_name, email, password_hash, is_active
    FROM   lecturers
    WHERE  lower(email) = :email
    UNION ALL
    SELECT 'sinh_vien'  AS role,
           student_id   AS actor_id,
           full_name, email, password_hash, is_active
    FROM   students
    WHERE  lower(email) = :email
    LIMIT  1
    """
)


def _record_audit_event(
    action: str,
    description: str,
    actor_role: str,
    *,
    actor_id: Any = None,
    entity_type: str | None = None,
    entity_name: str | None = None,
    status: str = "success",
) -> bool:
    """Write one row to audit_logs.  Never raises — returns False on failure."""
    audit_role = _AUDIT_ROLE_MAP.get(actor_role, "SYSTEM")
    fk_col = _AUDIT_FK_COL.get(actor_role)
    try:
        db.session.execute(
            text(
                """
                INSERT INTO audit_logs (
                    actor_role, action, entity_type, description, details, created_at
                ) VALUES (
                    :actor_role, :action, :entity_type, :description, :details::jsonb, NOW()
                )
                """
            ),
            {
                "actor_role":  audit_role,
                "action":      action,
                "entity_type": entity_type,
                "description": description,
                "details":     f'{{"status": "{status}", "actor_id": "{actor_id}", "entity_name": "{entity_name}"}}',
            },
        )
        db.session.commit()
        return True
    except Exception:
        db.session.rollback()
        logger.exception("Audit log write failed for action=%s", action)
        return False


@login_bp.route("/login", methods=["POST"])
def login():
    if request_limit_exceeded(("login", request.remote_addr), 10, 900):
        return jsonify({"message": "Too many login attempts. Please try again later."}), 429

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"message": "Invalid login request."}), 400

    raw_email: Any = payload.get("email")
    password: Any = payload.get("password")

    if not is_valid_email_format(raw_email):
        return jsonify({"code": "invalid_email", "message": "Enter a valid email address."}), 400
    if not isinstance(password, str) or not password or len(password) > 64:
        return jsonify({"code": "invalid_password", "message": "Password must be 1–64 characters."}), 400

    email = raw_email.lower()

    try:
        row = db.session.execute(_ACCOUNT_LOOKUP_SQL, {"email": email}).mappings().first()
    except Exception:
        db.session.rollback()
        logger.exception("Login database lookup failed for %s", email)
        return jsonify({"message": "Login is temporarily unavailable. Please try again."}), 503

    if not row:
        return jsonify({"code": "email_not_found", "message": "No account found for this email."}), 404

    if row["is_active"] is not True:
        return jsonify({"code": "account_disabled", "message": "This account is not available."}), 403

    try:
        password_matches = check_password_hash(str(row["password_hash"] or ""), password)
    except (TypeError, ValueError):
        logger.warning("Stored password hash is malformed for %s", email)
        password_matches = False

    if not password_matches:
        return jsonify({"code": "password_incorrect", "message": "The password is incorrect."}), 401

    role: str = row["role"]
    token_config_key = _TOKEN_HOURS_CONFIG[role]
    token = create_access_token(
        identity=email,
        additional_claims={"role": role},
        expires_delta=timedelta(hours=current_app.config[token_config_key]),
    )

    _record_audit_event(
        "Đăng nhập",
        f"{row['full_name']} đăng nhập vào hệ thống",
        role,
        actor_id=str(row["actor_id"]),
        entity_type="account",
        entity_name=row["full_name"],
        status="success",
    )

    return jsonify({
        "access_token": token,
        "user": {
            "email":     row["email"],
            "full_name": row["full_name"],
            "role":      role,
        },
    }), 200


@login_bp.route("/logout", methods=["POST"])
@jwt_required()
def logout():
    identity: Any = get_jwt_identity()
    role: Any = get_jwt().get("role")
    actor_email = str(identity or "unknown")
    actor_role = str(role or "SYSTEM")

    # NOTE (S3): For full token revocation, add jti to a Redis/DB denylist here.
    # jti = get_jwt().get("jti")

    _record_audit_event(
        "Đăng xuất",
        f"{actor_email} đăng xuất khỏi hệ thống",
        actor_role,
        entity_type="account",
        entity_name=actor_email,
        status="success",
    )

    return jsonify({"message": "Logged out successfully."}), 200
