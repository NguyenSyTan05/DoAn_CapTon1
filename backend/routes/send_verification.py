import smtplib

from flask import Blueprint, current_app, jsonify, request

from account_service import account_email_exists
from email_utils import is_valid_email_format
from extensions import db
from request_limits import request_limit_exceeded
from verification_service import (
    EmailValidationServiceError,
    challenge_ttl_seconds,
    check_challenge_cooldown,
    create_otp_challenge,
    generate_number_choices,
    is_dev_otp_fallback_enabled,
    send_verification_email,
    validate_email_deliverability,
)

send_verification_bp = Blueprint(
    "send_verification", __name__, url_prefix="/auth/verification"
)


@send_verification_bp.route("/send", methods=["POST"])
def send_email_verification():
    if request_limit_exceeded(("verification-send", request.remote_addr), 5, 900):
        return jsonify({"message": "Too many verification requests. Please try again later."}), 429
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"message": "Enter a valid email address."}), 400
    email_value = payload.get("email", "")
    if not isinstance(email_value, str):
        return jsonify({"message": "Enter a valid email address."}), 400
    email = email_value.strip().lower()
    if not is_valid_email_format(email):
        return jsonify({"message": "Enter a valid email address."}), 400

    try:
        if account_email_exists(email):
            return jsonify({
                "code": "email_already_registered",
                "message": "This email is already registered.",
            }), 409
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to check registration email availability")
        return jsonify({"message": "Could not check the email. Please try again."}), 500

    try:
        email_status = validate_email_deliverability(email)
    except EmailValidationServiceError as error:
        current_app.logger.warning(
            "Email validation provider request failed (%s)", error.code
        )
        if error.code == "email_validation_configuration_error":
            message = "Email validation API key is missing or invalid."
        elif error.code == "email_validation_quota_exceeded":
            message = "The email validation API quota has been reached."
        elif error.code == "email_validation_rate_limited":
            message = "The email validation API request limit was reached. Please retry shortly."
        else:
            message = "Could not verify this email right now. Please try again."
        return jsonify({
            "code": error.code,
            "message": message,
        }), 503
    if email_status == "invalid":
        return jsonify({
            "code": "email_not_found",
            "message": "This email address does not appear to exist or receive mail.",
        }), 422
    if email_status not in ("valid", "unknown"):
        return jsonify({
            "code": "email_could_not_verify",
            "message": "This email could not be verified. Check it or try another address.",
        }), 422

    if email_status == "unknown":
        current_app.logger.warning(
            "Email validation was inconclusive for %s; continuing with verification send.",
            email,
        )

    retry_after = check_challenge_cooldown(email, "REGISTER")
    if retry_after > 0:
        return jsonify({
            "message": "Please wait before requesting another verification email.",
            "retryAfter": retry_after,
        }), 429

    code, choices = generate_number_choices()

    try:
        send_verification_email(email, code)
    except smtplib.SMTPRecipientsRefused:
        return jsonify({
            "code": "email_not_found",
            "message": "The email address could not be found or does not accept mail.",
        }), 422
    except (OSError, smtplib.SMTPException, RuntimeError):
        current_app.logger.exception("Failed to send registration verification email")
        return jsonify({
            "message": "Could not send the verification email. Check SMTP configuration and try again.",
        }), 503

    try:
        challenge_id = create_otp_challenge(email, "REGISTER", code, choices, role="student")
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to persist registration verification challenge")
        return jsonify({"message": "Could not start verification right now. Please try again."}), 500

    resp_body = {
        "challengeId": challenge_id,
        "choices": choices,
        "expiresIn": challenge_ttl_seconds,
    }
    if is_dev_otp_fallback_enabled():
        resp_body["devCode"] = code
    return jsonify(resp_body), 200
