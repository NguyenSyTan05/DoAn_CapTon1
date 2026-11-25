"""Kiểm tra vai trò trong JWT dùng chung cho các route.

Token do /auth/login cấp: identity = email, claim "role" thuộc
ADMIN_ROLE / LECTURER_ROLE / STUDENT_ROLE. ai-service cũng xác minh các token
này bằng cùng SECRET_KEY (HS256), nên không được đổi tên hay giá trị claim.
"""

from functools import wraps

from flask import jsonify, request
from flask_jwt_extended import get_jwt, jwt_required
from flask_jwt_extended.config import config as jwt_config


ADMIN_ROLE = "admin"
LECTURER_ROLE = "giang_vien"
STUDENT_ROLE = "sinh_vien"
# "student" là giá trị cũ vẫn được chấp nhận ở các route sinh viên.
STUDENT_ROLES = (STUDENT_ROLE, "student")

# Thông báo cũ của các route admin/giảng viên, giữ nguyên để frontend không đổi.
ADMIN_REQUIRED_MESSAGE = "Administrator access is required."
LECTURER_REQUIRED_MESSAGE = "Không tìm thấy tài khoản giảng viên."
DEFAULT_FORBIDDEN_MESSAGE = "Bạn không có quyền truy cập chức năng này."
ROLE_FORBIDDEN_CODE = "role_forbidden"


def current_role():
    """Claim "role" của JWT đã được xác minh trong request hiện tại."""
    return get_jwt().get("role")


def role_denied(*roles, message=DEFAULT_FORBIDDEN_MESSAGE, code=ROLE_FORBIDDEN_CODE):
    """Trả về response 403 nếu vai trò trong JWT không thuộc `roles`, ngược lại None.

    Dùng trực tiếp trong thân route khi route cần kiểm tra dữ liệu đầu vào
    trước khi kiểm tra vai trò (giữ nguyên thứ tự phản hồi cũ). Phải được gọi
    sau khi JWT đã được xác minh (@jwt_required hoặc @role_required).
    """
    if current_role() in roles:
        return None
    return jsonify({"message": message, "code": code}), 403


def role_required(*roles, message=DEFAULT_FORBIDDEN_MESSAGE, code=ROLE_FORBIDDEN_CODE):
    """Decorator thay cho @jwt_required(): thiếu/sai token -> 401 (mặc định
    của flask-jwt-extended), vai trò không nằm trong `roles` -> 403
    {"message": ..., "code": ...}.
    """
    if not roles:
        raise ValueError("role_required cần ít nhất một vai trò.")

    def decorator(fn):
        @wraps(fn)
        @jwt_required()
        def wrapper(*args, **kwargs):
            # jwt_required bỏ qua xác minh cho các method miễn trừ (OPTIONS).
            if request.method in jwt_config.exempt_methods:
                return fn(*args, **kwargs)
            denied = role_denied(*roles, message=message, code=code)
            if denied:
                return denied
            return fn(*args, **kwargs)

        return wrapper

    return decorator
