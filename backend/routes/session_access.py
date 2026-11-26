"""Kiểm tra quyền vào một phiên học, dành cho ai-service gọi sang.

GET /auth/sessions/<session_id>/access   (Authorization: Bearer <token>)

200 {"session_id": "<id>", "role": "<role trong JWT>", "access": "lecturer" | "student" | "admin"}
    lecturer: giảng viên sở hữu lớp của phiên;
    student : sinh viên đã tham gia lớp (class_members ACTIVE);
    admin   : mọi quản trị viên đang hoạt động (chỉ quan sát).
400 {"code": "invalid_session_id"}   session_id không phải UUID
401                                  thiếu/sai token (mặc định flask-jwt-extended)
403 {"code": "session_forbidden"}    không liên quan tới phiên
403 {"code": "session_closed"}       phiên đã ENDED/CANCELLED (giảng viên, sinh viên);
                                     quản trị viên vẫn được 200 (chỉ quan sát)
404 {"code": "session_not_found"}    không có phiên này
503 {"code": "session_access_unavailable"}  lỗi cơ sở dữ liệu
"""

from uuid import UUID

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt, get_jwt_identity, jwt_required
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from auth_utils import ADMIN_ROLE, LECTURER_ROLE, STUDENT_ROLES
from extensions import db


session_access_bp = Blueprint(
    "session_access", __name__, url_prefix="/auth/sessions"
)

# Chỉ dùng tham số ràng buộc; không ghép chuỗi người dùng vào SQL.
SESSION_STATUS_SQL = text(
    "SELECT status FROM sessions WHERE session_id = :session_id"
)
# Phiên đã đóng: không ai vào lại được, trừ quản trị viên (chỉ quan sát).
CLOSED_STATUSES = frozenset({"ENDED", "CANCELLED"})
ADMIN_ACCESS_SQL = text(
    """
    SELECT 1
    FROM admins
    WHERE lower(email) = lower(:email) AND is_active = TRUE
    """
)
LECTURER_ACCESS_SQL = text(
    """
    SELECT 1
    FROM sessions s
    JOIN classes c ON c.class_id = s.class_id
    JOIN lecturers l ON l.lecturer_id = c.lecturer_id
    WHERE s.session_id = :session_id
      AND c.status = 'ACTIVE'
      AND lower(l.email) = lower(:email)
      AND l.is_active = TRUE
    """
)
STUDENT_ACCESS_SQL = text(
    """
    SELECT 1
    FROM sessions s
    JOIN classes c ON c.class_id = s.class_id
    JOIN class_members cm ON cm.class_id = c.class_id
    JOIN students st ON st.student_id = cm.student_id
    WHERE s.session_id = :session_id
      AND c.status = 'ACTIVE'
      AND upper(cm.status) = 'ACTIVE'
      AND lower(st.email) = lower(:email)
      AND st.is_active = TRUE
    """
)


def _error(code, status):
    return jsonify({"code": code}), status


@session_access_bp.route("/<session_id>/access", methods=["GET"])
@jwt_required()
def get_session_access(session_id):
    try:
        normalized_id = str(UUID(session_id))
    except (ValueError, TypeError, AttributeError):
        return _error("invalid_session_id", 400)

    role = get_jwt().get("role")
    email = get_jwt_identity()
    if role == ADMIN_ROLE:
        access, statement = "admin", ADMIN_ACCESS_SQL
    elif role == LECTURER_ROLE:
        access, statement = "lecturer", LECTURER_ACCESS_SQL
    elif role in STUDENT_ROLES:
        access, statement = "student", STUDENT_ACCESS_SQL
    else:
        return _error("session_forbidden", 403)
    if not isinstance(email, str) or not email:
        return _error("session_forbidden", 403)

    params = {"session_id": normalized_id, "email": email}
    if access == "admin":
        params = {"email": email}
    try:
        session_row = db.session.execute(
            SESSION_STATUS_SQL, {"session_id": normalized_id}
        ).first()
        if not session_row:
            return _error("session_not_found", 404)
        allowed = db.session.execute(statement, params).first()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Session access lookup failed")
        return _error("session_access_unavailable", 503)

    if not allowed:
        return _error("session_forbidden", 403)
    # Chỉ báo "đã đóng" cho người có liên quan tới phiên (không lộ trạng thái cho người ngoài).
    # Với allow_closed=1 (xem lại tóm tắt/phụ đề sau buổi học), cho phép phiên ENDED nhưng vẫn chặn CANCELLED.
    status_upper = str(session_row[0] or "").upper()
    allow_closed = request.args.get("allow_closed") in ("1", "true")
    closed = status_upper in CLOSED_STATUSES
    if closed and access != "admin":
        if not (allow_closed and status_upper == "ENDED"):
            return _error("session_closed", 403)

    return jsonify({
        "session_id": normalized_id,
        "role": role,
        "access": access,
    }), 200
