import re

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy import text

from account_service import account_email_exists
from email_utils import is_valid_email_format
from extensions import db
from request_limits import request_limit_exceeded

check_registration_email_bp = Blueprint(
    "check_registration_email", __name__, url_prefix="/auth"
)


@check_registration_email_bp.route("/email/check", methods=["POST"])
def check_registration_email():
    if request_limit_exceeded(("email-check", request.remote_addr), 20, 900):
        return jsonify({
            "code": "email_check_rate_limited",
            "message": "Bạn thao tác quá nhanh. Vui lòng thử lại sau ít phút.",
        }), 429
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"message": "Vui lòng nhập địa chỉ email hợp lệ."}), 400

    email_value = payload.get("email", "")
    student_code = payload.get("studentCode", "")
    if not isinstance(email_value, str):
        return jsonify({"message": "Vui lòng nhập địa chỉ email hợp lệ."}), 400
    email = email_value.strip().lower()
    if not is_valid_email_format(email):
        return jsonify({"message": "Vui lòng nhập địa chỉ email hợp lệ."}), 400

    try:
        if account_email_exists(email):
            return jsonify({
                "code": "email_already_registered",
                "message": "Email này đã có tài khoản ClassBridge. Vui lòng đăng nhập.",
            }), 409

        if isinstance(student_code, str) and re.fullmatch(r"\d{11}", student_code.strip()):
            code_exists = db.session.execute(
                text("SELECT EXISTS (SELECT 1 FROM students WHERE student_code = :code)"),
                {"code": student_code.strip()},
            ).scalar_one()
            if code_exists:
                return jsonify({
                    "code": "student_code_already_registered",
                    "message": "Mã số sinh viên này đã được đăng ký.",
                }), 409
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to check registration availability")
        return jsonify({"message": "Không thể kiểm tra thông tin lúc này. Vui lòng thử lại."}), 500

    return jsonify({"available": True}), 200
