import smtplib

from flask import Blueprint, current_app, jsonify, request

from extensions import db
from request_limits import request_limit_exceeded
from verification_service import (
    challenge_ttl_seconds,
    check_selected_number,
    generate_number_choices,
    is_dev_otp_fallback_enabled,
    load_otp_challenge,
    mark_registration_verified,
    rotate_wrong_otp_choice,
    send_verification_email,
)

verify_verification_bp = Blueprint(
    "verify_verification", __name__, url_prefix="/auth/verification"
)


@verify_verification_bp.route("/verify", methods=["POST"])
def verify_email_code():
    if request_limit_exceeded(("verification-check", request.remote_addr), 20, 900):
        return jsonify({"message": "Too many verification attempts. Please try again later."}), 429
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"message": "Invalid verification request."}), 400
    challenge_id = payload.get("challengeId")
    selected_number = payload.get("selectedNumber")
    if not isinstance(challenge_id, str) or not challenge_id:
        return jsonify({"message": "Verification expired. Request a new email code."}), 400

    challenge = load_otp_challenge(challenge_id, "REGISTER")
    if not challenge:
        return jsonify({"message": "Verification expired. Request a new email code."}), 400

    if type(selected_number) is not int or selected_number not in challenge["choices"]:
        return jsonify({"message": "Select one of the displayed numbers."}), 400

    if challenge.get("verified"):
        return jsonify({"verified": True}), 200

    if not check_selected_number(challenge, selected_number):
        new_code, new_choices = generate_number_choices()

        try:
            send_verification_email(challenge["email"], new_code)
        except smtplib.SMTPRecipientsRefused:
            return jsonify({
                "code": "email_not_found",
                "message": "The email address could not be found or does not accept mail.",
            }), 422
        except (OSError, smtplib.SMTPException, RuntimeError):
            current_app.logger.exception("Failed to resend registration verification email")
            return jsonify({
                "message": "Could not resend the verification email. Please try again.",
            }), 503

        try:
            rotate_wrong_otp_choice(challenge_id, challenge, "REGISTER", new_code, new_choices)
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Failed to update registration OTP attempt")
            return jsonify({"message": "Could not update verification challenge."}), 500

        resp_body = {
            "verified": False,
            "message": "That number did not match. A new verification number was emailed.",
            "choices": new_choices,
            "expiresIn": challenge_ttl_seconds,
        }
        if is_dev_otp_fallback_enabled():
            resp_body["devCode"] = new_code
        return jsonify(resp_body), 200

    try:
        mark_registration_verified(challenge_id, challenge)
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to mark registration OTP as verified")
        return jsonify({"message": "Could not verify email right now."}), 500

    return jsonify({"verified": True}), 200
