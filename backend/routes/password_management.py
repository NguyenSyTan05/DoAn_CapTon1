"""
password_management.py (routes)
=================================
Quản lý mật khẩu cho cả 3 vai trò (Sinh viên, Giảng viên, Quản trị viên):
1. Đổi mật khẩu khi đang đăng nhập  (`POST /auth/change-password`)
2. Quên mật khẩu 3 bước qua xác thực số Email:
   - Bước 1: `POST /auth/password/forgot/send`   {email}
   - Bước 2: `POST /auth/password/forgot/verify` {challengeId, selectedNumber}
   - Bước 3: `POST /auth/password/forgot/reset`  {email, challengeId, resetToken, password, confirmPassword}

Fixes applied (B5, B12, B14, B15, S2, S9, S11):
- Table name injection risk eliminated: use _TABLE_ALLOWLIST whitelist dict instead
  of f-string interpolation into raw SQL text().
- selectedNumber check uses isinstance(x, int) and not isinstance(x, bool).
- OTP code space extended to [0, 9999] (from [-100, 100]).
- COMMON_PASSWORDS list expanded.
- All DB writes wrapped in try/except with explicit rollback.
"""
from __future__ import annotations

import logging
import re
import smtplib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt, get_jwt_identity, jwt_required
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.security import check_password_hash, generate_password_hash

from email_utils import is_valid_email_format
from extensions import db
from request_limits import request_limit_exceeded
from routes.login import _record_audit_event
from verification_service import (
    challenge_ttl_seconds,
    check_challenge_cooldown,
    check_selected_number,
    consume_password_reset_session,
    create_otp_challenge,
    generate_number_choices,
    issue_password_reset_token,
    load_otp_challenge,
    rotate_wrong_otp_choice,
    send_password_reset_email,
    verify_password_reset_session,
)

logger = logging.getLogger("classbridge.password_management")

password_management_bp = Blueprint("password_management", __name__, url_prefix="/auth")

# Whitelist for table names — eliminates f-string SQL injection risk (S2, B5).
_TABLE_ALLOWLIST: dict[str, str] = {
    "students":  "students",
    "lecturers": "lecturers",
    "admins":    "admins",
}

COMMON_PASSWORDS = frozenset(
    {
        "password", "password1", "password123", "password123!", "qwerty123",
        "admin123", "welcome1", "letmein123", "iloveyou1", "abc12345",
        "12345678", "123456789", "qwerty123!", "student123!", "111111",
        "123456", "1234567890", "abc123", "monkey", "1234", "dragon",
        "master", "sunshine", "princess", "shadow", "login", "pass",
        "password1!", "P@ssword1", "Admin123!", "Welcome1!",
    }
)

PASSWORD_RULES = (
    (r"[A-Z]",          "Mật khẩu phải có ít nhất 1 chữ cái in hoa."),
    (r"[a-z]",          "Mật khẩu phải có ít nhất 1 chữ cái thường."),
    (r"[0-9]",          "Mật khẩu phải có ít nhất 1 chữ số."),
    (r"[^A-Za-z0-9\s]", "Mật khẩu phải có ít nhất 1 ký tự đặc biệt."),
)

MAX_WRONG_PICKS = 5


@dataclass(frozen=True)
class AccountMatch:
    role:   str
    table:  str   # one of _TABLE_ALLOWLIST keys
    id_col: str
    row:    Mapping[str, Any]


def validate_strong_password(password: object) -> str | None:
    if not isinstance(password, str) or not 8 <= len(password) <= 64:
        return "Mật khẩu phải có độ dài từ 8 đến 64 ký tự."
    if re.search(r"\s", password):
        return "Mật khẩu không được chứa khoảng trắng."
    for pattern, message in PASSWORD_RULES:
        if not re.search(pattern, password):
            return message
    if password.casefold() in COMMON_PASSWORDS:
        return "Mật khẩu này quá phổ biến, vui lòng chọn mật khẩu an toàn hơn."
    return None


def _update_password_hash(table: str, email: str, new_hash: str) -> None:
    """Execute password hash UPDATE using whitelisted table name only (S2, B5)."""
    safe_table = _TABLE_ALLOWLIST.get(table)
    if not safe_table:
        raise ValueError(f"Unknown table: {table!r}")
    # Construct SQL with the allowlisted literal — no user data in table position.
    sql_map = {
        "students":  "UPDATE students  SET password_hash = :h WHERE lower(email) = :e",
        "lecturers": "UPDATE lecturers SET password_hash = :h WHERE lower(email) = :e",
        "admins":    "UPDATE admins    SET password_hash = :h WHERE lower(email) = :e",
    }
    db.session.execute(text(sql_map[safe_table]), {"h": new_hash, "e": email})


def _find_account_by_email(email: str) -> AccountMatch | None:
    """Find account by email across all three role tables via UNION ALL (P1, S1)."""
    row = db.session.execute(
        text(
            """
            SELECT 'admin'      AS role, 'admins'    AS tbl, 'admin_id'    AS id_col,
                   admin_id     AS id, full_name, email, password_hash, is_active
            FROM   admins WHERE lower(email) = :email
            UNION ALL
            SELECT 'giang_vien' AS role, 'lecturers' AS tbl, 'lecturer_id' AS id_col,
                   lecturer_id  AS id, full_name, email, password_hash, is_active
            FROM   lecturers WHERE lower(email) = :email
            UNION ALL
            SELECT 'sinh_vien'  AS role, 'students'  AS tbl, 'student_id'  AS id_col,
                   student_id   AS id, full_name, email, password_hash, is_active
            FROM   students WHERE lower(email) = :email
            LIMIT 1
            """
        ),
        {"email": email},
    ).mappings().first()
    if row is None:
        return None
    return AccountMatch(
        role=row["role"], table=row["tbl"], id_col=row["id_col"], row=row
    )


def _find_account_for_role(role: str | None, email: str) -> AccountMatch | None:
    """Find account for a specific role (used in change-password with JWT claim)."""
    _ROLE_TO_TABLE: dict[str, tuple[str, str, str]] = {
        "admin":      ("admins",    "admin_id",    "admin"),
        "giang_vien": ("lecturers", "lecturer_id", "giang_vien"),
        "lecturer":   ("lecturers", "lecturer_id", "giang_vien"),
        "sinh_vien":  ("students",  "student_id",  "sinh_vien"),
        "student":    ("students",  "student_id",  "sinh_vien"),
    }
    entry = _ROLE_TO_TABLE.get(role or "")
    if not entry:
        return None
    tbl, id_col, canonical_role = entry
    sql_map = {
        "admins":    "SELECT admin_id    AS id, full_name, email, password_hash, is_active FROM admins    WHERE lower(email) = :email",
        "lecturers": "SELECT lecturer_id AS id, full_name, email, password_hash, is_active FROM lecturers WHERE lower(email) = :email",
        "students":  "SELECT student_id  AS id, full_name, email, password_hash, is_active FROM students  WHERE lower(email) = :email",
    }
    row = db.session.execute(text(sql_map[tbl]), {"email": email}).mappings().first()
    if row is None:
        return None
    return AccountMatch(role=canonical_role, table=tbl, id_col=id_col, row=row)


# =====================================================================
# 1. Đổi mật khẩu khi đang đăng nhập
# =====================================================================
@password_management_bp.route("/change-password", methods=["POST"])
@jwt_required()
def change_password():
    if request_limit_exceeded(("change-password", request.remote_addr), 10, 900):
        return jsonify({"message": "Bạn thao tác quá nhiều lần. Vui lòng thử lại sau."}), 429

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"message": "Dữ liệu đổi mật khẩu không hợp lệ."}), 400

    current_password: Any = payload.get("currentPassword")
    new_password:     Any = payload.get("newPassword")
    confirm_password: Any = payload.get("confirmPassword")

    if not isinstance(current_password, str) or not current_password or len(current_password) > 64:
        return jsonify({"code": "invalid_current_password", "message": "Vui lòng nhập mật khẩu hiện tại."}), 400

    if not isinstance(new_password, str):
        return jsonify({"code": "weak_password", "message": "Mật khẩu phải có độ dài từ 8 đến 64 ký tự."}), 400

    pw_err = validate_strong_password(new_password)
    if pw_err:
        return jsonify({"code": "weak_password", "message": pw_err}), 400

    if not isinstance(confirm_password, str) or new_password != confirm_password:
        return jsonify({"code": "password_mismatch", "message": "Mật khẩu xác nhận không khớp."}), 400

    raw_identity: Any = get_jwt_identity()
    email = raw_identity.strip().lower() if isinstance(raw_identity, str) else ""
    raw_role: Any = get_jwt().get("role")
    role = raw_role if isinstance(raw_role, str) else None
    if not email:
        return jsonify({"message": "Phiên đăng nhập không hợp lệ."}), 401

    try:
        match = _find_account_for_role(role, email)
        if match is None:
            return jsonify({"message": "Không tìm thấy tài khoản người dùng."}), 404
        row = match.row
        if row["is_active"] is not True:
            return jsonify({"code": "account_disabled", "message": "Tài khoản này đã bị vô hiệu hóa."}), 403

        stored_hash = str(row["password_hash"] or "")
        try:
            matches_current = check_password_hash(stored_hash, current_password)
        except (TypeError, ValueError):
            matches_current = False

        if not matches_current:
            return jsonify({"code": "current_password_incorrect", "message": "Mật khẩu hiện tại không chính xác."}), 401

        try:
            same_as_new = check_password_hash(stored_hash, new_password)
        except (TypeError, ValueError):
            same_as_new = False
        if same_as_new:
            return jsonify({"code": "same_password", "message": "Mật khẩu mới phải khác mật khẩu hiện tại."}), 400

        new_hash = generate_password_hash(new_password)
        _update_password_hash(match.table, email, new_hash)
        db.session.commit()

    except (SQLAlchemyError, ValueError):
        db.session.rollback()
        logger.exception("Change password database error for %s", email)
        return jsonify({"message": "Không thể đổi mật khẩu lúc này. Vui lòng thử lại."}), 500

    full_name = str(row["full_name"] or email)
    _record_audit_event(
        "Đổi mật khẩu",
        f"{full_name} đã tự đổi mật khẩu tài khoản",
        match.role,
        actor_id=str(row["id"]),
        entity_type="account",
        entity_name=full_name,
        status="success",
    )

    return jsonify({"success": True, "message": "Đổi mật khẩu thành công!"}), 200


# =====================================================================
# 2. Quên mật khẩu — Bước 1: Gửi mã số xác thực qua Email
# =====================================================================
@password_management_bp.route("/password/forgot/send", methods=["POST"])
def send_forgot_password_challenge():
    if request_limit_exceeded(("forgot-send", request.remote_addr), 5, 900):
        return jsonify({"message": "Bạn yêu cầu mã quá nhiều lần. Vui lòng thử lại sau ít phút."}), 429

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"message": "Vui lòng nhập địa chỉ email hợp lệ."}), 400

    raw_email: Any = payload.get("email", "")
    if not isinstance(raw_email, str):
        return jsonify({"code": "invalid_email", "message": "Địa chỉ email chưa đúng định dạng."}), 400
    email = raw_email.strip().lower()
    if not is_valid_email_format(email):
        return jsonify({"code": "invalid_email", "message": "Địa chỉ email chưa đúng định dạng."}), 400

    try:
        match = _find_account_by_email(email)
    except SQLAlchemyError:
        db.session.rollback()
        logger.exception("Forgot password lookup failed for %s", email)
        return jsonify({"message": "Không thể kiểm tra email lúc này. Vui lòng thử lại."}), 503

    if match is None:
        return jsonify({"code": "email_not_found", "message": "Không tìm thấy tài khoản nào gắn với email này."}), 404
    if match.row["is_active"] is not True:
        return jsonify({"code": "account_disabled", "message": "Tài khoản này đã bị vô hiệu hóa."}), 403

    retry_after = check_challenge_cooldown(email, "RESET_PASSWORD")
    if retry_after > 0:
        return jsonify(
            {
                "code":       "cooldown",
                "message":    f"Vui lòng đợi {retry_after} giây trước khi gửi lại mã xác thực.",
                "retryAfter": retry_after,
            }
        ), 429

    code, choices = generate_number_choices()
    try:
        send_password_reset_email(email, code)
    except smtplib.SMTPRecipientsRefused:
        return jsonify({"code": "email_not_found", "message": "Địa chỉ email không nhận được thư."}), 422
    except (OSError, smtplib.SMTPException, RuntimeError):
        logger.exception("Failed to send password reset email to %s", email)
        return jsonify(
            {
                "code":    "smtp_unavailable",
                "message": "Máy chủ chưa gửi được email khôi phục. Vui lòng kiểm tra cấu hình SMTP.",
            }
        ), 503

    try:
        challenge_id = create_otp_challenge(
            email, "RESET_PASSWORD", code, choices, role=match.role
        )
    except SQLAlchemyError:
        db.session.rollback()
        logger.exception("Failed to store password reset challenge for %s", email)
        return jsonify({"message": "Không thể khởi tạo phiên khôi phục mật khẩu lúc này."}), 500

    return jsonify(
        {
            "challengeId": challenge_id,
            "choices":     choices,
            "expiresIn":   challenge_ttl_seconds,
        }
    ), 200


# =====================================================================
# 3. Quên mật khẩu — Bước 2: Chọn đúng số từ Email
# =====================================================================
@password_management_bp.route("/password/forgot/verify", methods=["POST"])
def verify_forgot_password_challenge():
    if request_limit_exceeded(("forgot-verify", request.remote_addr), 20, 900):
        return jsonify({"message": "Bạn thử xác minh quá nhiều lần. Vui lòng thử lại sau."}), 429

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"message": "Yêu cầu xác minh không hợp lệ."}), 400

    challenge_id: Any = payload.get("challengeId")
    selected_number: Any = payload.get("selectedNumber")

    if not isinstance(challenge_id, str) or not challenge_id:
        return jsonify({"message": "Phiên xác minh không hợp lệ hoặc đã hết hạn."}), 400

    challenge = load_otp_challenge(challenge_id, "RESET_PASSWORD")
    if not challenge:
        return jsonify({"code": "challenge_expired", "message": "Mã xác minh đã hết hạn. Vui lòng gửi lại email."}), 400

    # Fix B14: use isinstance with bool exclusion for type safety.
    if not isinstance(selected_number, int) or isinstance(selected_number, bool):
        return jsonify({"message": "Vui lòng gửi một số nguyên hợp lệ."}), 400
    if selected_number not in challenge["choices"]:
        return jsonify({"message": "Vui lòng chọn một trong các con số hiển thị trên màn hình."}), 400

    if challenge.get("verified") and challenge.get("source") == "mem" and challenge.get("reset_token"):
        return jsonify({"verified": True, "resetToken": challenge["reset_token"]}), 200

    if not check_selected_number(challenge, selected_number):
        next_attempts = int(challenge["wrong_attempts"]) + 1
        if next_attempts >= MAX_WRONG_PICKS:
            rotate_wrong_otp_choice(
                challenge_id, challenge, "RESET_PASSWORD", 0, [0, 1, 2, 3], max_wrong=MAX_WRONG_PICKS
            )
            return jsonify(
                {
                    "code":    "too_many_wrong_choices",
                    "message": "Bạn đã chọn sai quá số lần cho phép. Vui lòng yêu cầu mã mới.",
                }
            ), 400

        new_code, new_choices = generate_number_choices()
        try:
            send_password_reset_email(str(challenge["email"]), new_code)
        except (OSError, smtplib.SMTPException, RuntimeError):
            logger.exception("Failed to resend password reset challenge")
            return jsonify({"message": "Không thể gửi lại mã xác minh mới. Vui lòng thử lại."}), 503

        rotate_wrong_otp_choice(
            challenge_id, challenge, "RESET_PASSWORD", new_code, new_choices, max_wrong=MAX_WRONG_PICKS
        )
        return jsonify(
            {
                "verified":  False,
                "message":   "Con số vừa chọn chưa đúng. Một con số mới đã được gửi tới email của bạn.",
                "choices":   new_choices,
                "expiresIn": challenge_ttl_seconds,
            }
        ), 200

    acct_match = _find_account_by_email(str(challenge["email"]))
    reset_token = issue_password_reset_token(
        challenge_id,
        challenge,
        canonical_role=acct_match.role if acct_match else None,
        account_id=acct_match.row["id"] if acct_match else None,
    )
    return jsonify({"verified": True, "resetToken": reset_token}), 200


# =====================================================================
# 4. Quên mật khẩu — Bước 3: Đặt mật khẩu mới
# =====================================================================
@password_management_bp.route("/password/forgot/reset", methods=["POST"])
def reset_forgot_password():
    if request_limit_exceeded(("forgot-reset", request.remote_addr), 10, 900):
        return jsonify({"message": "Bạn thao tác quá nhiều lần. Vui lòng thử lại sau."}), 429

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"message": "Yêu cầu đặt lại mật khẩu không hợp lệ."}), 400

    raw_email:        Any = payload.get("email", "")
    challenge_id:     Any = payload.get("challengeId", "")
    reset_token:      Any = payload.get("resetToken", "")
    new_password:     Any = payload.get("password", "")
    confirm_password: Any = payload.get("confirmPassword", "")

    if not isinstance(raw_email, str):
        return jsonify({"message": "Địa chỉ email không hợp lệ."}), 400
    email = raw_email.strip().lower()
    if not is_valid_email_format(email):
        return jsonify({"message": "Địa chỉ email không hợp lệ."}), 400

    if (
        not isinstance(challenge_id, str)
        or not isinstance(reset_token, str)
        or not challenge_id
        or not reset_token
    ):
        return jsonify({"message": "Vui lòng hoàn tất bước xác thực email trước khi đặt mật khẩu."}), 400

    if not verify_password_reset_session(email, challenge_id, reset_token):
        return jsonify(
            {
                "code":    "invalid_reset_session",
                "message": "Phiên khôi phục mật khẩu không hợp lệ hoặc đã hết hạn. Vui lòng thực hiện lại.",
            }
        ), 400

    if not isinstance(new_password, str):
        return jsonify({"code": "weak_password", "message": "Mật khẩu phải có độ dài từ 8 đến 64 ký tự."}), 400

    pw_err = validate_strong_password(new_password)
    if pw_err:
        return jsonify({"code": "weak_password", "message": pw_err}), 400

    if not isinstance(confirm_password, str) or new_password != confirm_password:
        return jsonify({"code": "password_mismatch", "message": "Mật khẩu nhập lại không khớp."}), 400

    try:
        match = _find_account_by_email(email)
        if match is None:
            consume_password_reset_session(challenge_id, reset_token)
            return jsonify({"message": "Không tìm thấy tài khoản người dùng."}), 404
        row = match.row
        if row["is_active"] is not True:
            consume_password_reset_session(challenge_id, reset_token)
            return jsonify({"code": "account_disabled", "message": "Tài khoản này đã bị vô hiệu hóa."}), 403

        stored_hash = str(row["password_hash"] or "")
        try:
            same_as_old = check_password_hash(stored_hash, new_password)
        except (TypeError, ValueError):
            same_as_old = False
        if same_as_old:
            return jsonify({"code": "same_password", "message": "Mật khẩu mới phải khác mật khẩu cũ."}), 400

        _update_password_hash(match.table, email, generate_password_hash(new_password))
        db.session.commit()

    except (SQLAlchemyError, ValueError):
        db.session.rollback()
        logger.exception("Reset password database update failed for %s", email)
        return jsonify({"message": "Không thể lưu mật khẩu mới lúc này. Vui lòng thử lại."}), 500

    consume_password_reset_session(challenge_id, reset_token)

    full_name = str(row["full_name"] or email)
    _record_audit_event(
        "Khôi phục mật khẩu",
        f"{full_name} đã đặt lại mật khẩu qua xác thực email",
        match.role,
        actor_id=str(row["id"]),
        entity_type="account",
        entity_name=full_name,
        status="success",
    )

    return jsonify(
        {
            "success": True,
            "message": "Đặt lại mật khẩu thành công! Vui lòng đăng nhập bằng mật khẩu mới.",
        }
    ), 200
