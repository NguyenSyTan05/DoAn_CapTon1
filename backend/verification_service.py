"""
verification_service.py (backend)
==================================
OTP challenge + password-reset token service.

Fixes applied (B4, P4, S8, S9):
- has_otp_tables(): result is cached after first successful check to eliminate
  repeated sa_inspect calls on every rate-limit/OTP operation (P4).
- generate_number_choices(): code space extended to [0, 9999] (S9).
- Thread-safety note for sa_inspect added.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import smtplib
import ssl
import time
import uuid
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from threading import Lock
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from flask import current_app
from sqlalchemy import inspect as sa_inspect, text
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db

logger = logging.getLogger("classbridge.verification_service")

# ---------------------------------------------------------------------------
# Fallback in-memory stores (used when otp_verifications table is absent,
# e.g. in minimal unit-test SQLite environments).
# ---------------------------------------------------------------------------
verification_challenges: dict[str, dict[str, Any]] = {}
verification_send_times: dict[str, float] = {}
password_reset_challenges: dict[str, dict[str, Any]] = {}
password_reset_send_times: dict[str, float] = {}

challenge_ttl_seconds = 600
send_cooldown_seconds = 60

email_validation_cache: dict[str, tuple[float, str]] = {}
email_validation_cache_ttl_seconds = 300

ROLE_DB_NAMES: dict[str, str] = {
    "admin":      "ADMIN",
    "giang_vien": "LECTURER",
    "lecturer":   "LECTURER",
    "sinh_vien":  "STUDENT",
    "student":    "STUDENT",
}

# ---------------------------------------------------------------------------
# Cached OTP table existence check (P4, B4)
# ---------------------------------------------------------------------------
_otp_tables_cache: tuple[bool, bool] | None = None
_otp_tables_lock = Lock()


class EmailValidationServiceError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _is_postgres() -> bool:
    try:
        return db.engine.dialect.name == "postgresql"
    except Exception:
        return False


def has_otp_tables() -> tuple[bool, bool]:
    """Check whether otp_verifications and password_reset_tokens exist.

    Result is cached after the first successful inspection to avoid repeated
    sa_inspect calls (P4).  Cache is intentionally never invalidated at runtime
    because schema changes require a service restart.
    """
    global _otp_tables_cache
    with _otp_tables_lock:
        if _otp_tables_cache is not None:
            return _otp_tables_cache
        try:
            insp = sa_inspect(db.engine)
            result = (
                bool(insp.has_table("otp_verifications")),
                bool(insp.has_table("password_reset_tokens")),
            )
            _otp_tables_cache = result
            return result
        except Exception:
            logger.debug("has_otp_tables: schema inspection failed", exc_info=True)
            return False, False


def _db_dt(dt: datetime):
    return dt if _is_postgres() else dt.isoformat()


def _parse_db_dt(raw) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo is not None else raw.replace(tzinfo=timezone.utc)
    if isinstance(raw, str) and raw.strip():
        s = raw.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
    return None


def _split_challenge_id(challenge_id: str) -> tuple[str, str] | None:
    if not isinstance(challenge_id, str) or "." not in challenge_id:
        return None
    otp_id_part, secret_part = challenge_id.split(".", 1)
    try:
        norm_uuid = str(uuid.UUID(otp_id_part))
    except (ValueError, TypeError):
        return None
    if not secret_part or len(secret_part) < 12:
        return None
    return norm_uuid, secret_part


def generate_number_choices() -> tuple[int, list[int]]:
    """Generate a secret code and 4 choices in [0, 9999] (fix S9: larger space)."""
    code = secrets.randbelow(10000)
    choices: list[int] = [code]
    while len(choices) < 4:
        candidate = secrets.randbelow(10000)
        if candidate not in choices:
            choices.append(candidate)
    secrets.SystemRandom().shuffle(choices)
    return code, choices


# =====================================================================
# OTP & Password Reset persistent store (SQL + RAM fallback)
# =====================================================================

def check_challenge_cooldown(email: str, purpose: str) -> int:
    """Return seconds to wait (0 = send immediately)."""
    norm_email = email.strip().lower()
    has_otp, _ = has_otp_tables()
    if has_otp:
        try:
            row = db.session.execute(
                text(
                    """
                    SELECT created_at
                    FROM   otp_verifications
                    WHERE  lower(contact_value) = :email
                      AND  purpose = :purpose
                    ORDER  BY created_at DESC
                    LIMIT  1
                    """
                ),
                {"email": norm_email, "purpose": purpose},
            ).mappings().first()
            last_dt = _parse_db_dt(row["created_at"]) if row else None
            if last_dt is not None:
                elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds()
                if elapsed < send_cooldown_seconds:
                    return max(1, int(send_cooldown_seconds - elapsed))
            return 0
        except Exception:
            db.session.rollback()
            logger.debug("check_challenge_cooldown DB error, using RAM fallback", exc_info=True)

    now_mono = time.monotonic()
    mem_times = verification_send_times if purpose == "REGISTER" else password_reset_send_times
    last_sent = mem_times.get(norm_email)
    if last_sent is not None and now_mono - last_sent < send_cooldown_seconds:
        return max(1, int(send_cooldown_seconds - (now_mono - last_sent)))
    return 0


def create_otp_challenge(
    email: str,
    purpose: str,
    code: int,
    choices: list[int],
    *,
    role: str | None = None,
) -> str:
    """Store a new challenge in otp_verifications (or RAM fallback).
    Never stores raw code or secret in DB.
    """
    norm_email = email.strip().lower()
    role_db = ROLE_DB_NAMES.get(role or "", None)
    has_otp, _ = has_otp_tables()

    if has_otp:
        otp_id = str(uuid.uuid4())
        raw_secret = secrets.token_urlsafe(24)
        now_dt = datetime.now(timezone.utc)
        exp_dt = now_dt + timedelta(seconds=challenge_ttl_seconds)
        otp_payload = json.dumps(
            {
                "secret_sha256": _sha256_hex(raw_secret),
                "code_hash":     generate_password_hash(str(code)),
                "choices":       list(choices),
            }
        )
        id_expr = "CAST(:otp_id AS uuid)" if _is_postgres() else ":otp_id"
        db.session.execute(
            text(
                """
                UPDATE otp_verifications
                SET    consumed_at = :now_dt
                WHERE  lower(contact_value) = :email
                  AND  purpose = :purpose
                  AND  consumed_at IS NULL
                """
            ),
            {"now_dt": _db_dt(now_dt), "email": norm_email, "purpose": purpose},
        )
        db.session.execute(
            text(
                f"""
                INSERT INTO otp_verifications (
                    otp_id, contact_type, contact_value, purpose, role_requested,
                    otp_hash, expires_at, attempt_count, created_at
                ) VALUES (
                    {id_expr}, 'EMAIL', :email, :purpose, :role_db,
                    :otp_hash, :expires_at, 0, :created_at
                )
                """
            ),
            {
                "otp_id":     otp_id,
                "email":      norm_email,
                "purpose":    purpose,
                "role_db":    role_db,
                "otp_hash":   otp_payload,
                "expires_at": _db_dt(exp_dt),
                "created_at": _db_dt(now_dt),
            },
        )
        db.session.commit()
        return f"{otp_id}.{raw_secret}"

    # RAM fallback
    now_mono = time.monotonic()
    store = verification_challenges if purpose == "REGISTER" else password_reset_challenges
    send_times = verification_send_times if purpose == "REGISTER" else password_reset_send_times
    for cid, ch in list(store.items()):
        if ch.get("email") == norm_email or now_mono >= ch.get("expires_at", 0):
            store.pop(cid, None)

    cid = secrets.token_urlsafe(32)
    entry: dict[str, Any] = {
        "email":         norm_email,
        "code":          code,
        "choices":       list(choices),
        "expires_at":    now_mono + challenge_ttl_seconds,
        "verified":      False,
        "wrong_attempts": 0,
    }
    if purpose == "RESET_PASSWORD":
        entry["reset_token"] = None
    store[cid] = entry
    send_times[norm_email] = now_mono
    return cid


def load_otp_challenge(challenge_id: str, purpose: str) -> dict[str, Any] | None:
    has_otp, _ = has_otp_tables()
    if has_otp:
        parts = _split_challenge_id(challenge_id)
        if not parts:
            return None
        otp_id, raw_secret = parts
        id_pred = "otp_id = CAST(:otp_id AS uuid)" if _is_postgres() else "otp_id = :otp_id"
        row = db.session.execute(
            text(
                f"""
                SELECT otp_id, contact_value, purpose, otp_hash, expires_at,
                       verified_at, attempt_count, consumed_at
                FROM   otp_verifications
                WHERE  {id_pred} AND purpose = :purpose
                """
            ),
            {"otp_id": otp_id, "purpose": purpose},
        ).mappings().first()
        if not row or row["consumed_at"] is not None:
            return None
        exp_dt = _parse_db_dt(row["expires_at"])
        if exp_dt is None or datetime.now(timezone.utc) >= exp_dt:
            return None
        try:
            meta = json.loads(row["otp_hash"])
        except (TypeError, ValueError):
            return None
        expected_sha = meta.get("secret_sha256", "")
        if not expected_sha or not secrets.compare_digest(expected_sha, _sha256_hex(raw_secret)):
            return None
        return {
            "source":        "db",
            "otp_id":        otp_id,
            "raw_secret":    raw_secret,
            "email":         str(row["contact_value"]).strip().lower(),
            "choices":       list(meta.get("choices") or []),
            "code_hash":     meta.get("code_hash", ""),
            "rt_sha256":     meta.get("rt_sha256"),
            "verified":      row["verified_at"] is not None,
            "wrong_attempts": int(row["attempt_count"] or 0),
        }

    store = verification_challenges if purpose == "REGISTER" else password_reset_challenges
    ch = store.get(challenge_id)
    if not ch or time.monotonic() >= ch.get("expires_at", 0):
        store.pop(challenge_id, None)
        return None
    return {
        "source":        "mem",
        "challenge_id":  challenge_id,
        "email":         ch["email"],
        "choices":       list(ch["choices"]),
        "code":          ch["code"],
        "verified":      bool(ch.get("verified")),
        "wrong_attempts": int(ch.get("wrong_attempts", 0)),
        "reset_token":   ch.get("reset_token"),
    }


def check_selected_number(loaded_challenge: dict[str, Any], selected_number: int) -> bool:
    if loaded_challenge["source"] == "db":
        try:
            return bool(check_password_hash(loaded_challenge["code_hash"], str(selected_number)))
        except (TypeError, ValueError):
            return False
    return selected_number == loaded_challenge["code"]


def rotate_wrong_otp_choice(
    challenge_id: str,
    loaded_challenge: dict[str, Any],
    purpose: str,
    new_code: int,
    new_choices: list[int],
    *,
    max_wrong: int | None = None,
) -> tuple[bool, int]:
    attempts = int(loaded_challenge["wrong_attempts"]) + 1
    if loaded_challenge["source"] == "db":
        otp_id = loaded_challenge["otp_id"]
        id_pred = "otp_id = CAST(:otp_id AS uuid)" if _is_postgres() else "otp_id = :otp_id"
        now_dt = datetime.now(timezone.utc)
        if max_wrong is not None and attempts >= max_wrong:
            db.session.execute(
                text(
                    f"""
                    UPDATE otp_verifications
                    SET    attempt_count = :attempts, consumed_at = :now_dt
                    WHERE  {id_pred}
                    """
                ),
                {"attempts": attempts, "now_dt": _db_dt(now_dt), "otp_id": otp_id},
            )
            db.session.commit()
            return True, attempts

        new_meta = json.dumps(
            {
                "secret_sha256": _sha256_hex(loaded_challenge["raw_secret"]),
                "code_hash":     generate_password_hash(str(new_code)),
                "choices":       list(new_choices),
            }
        )
        exp_dt = now_dt + timedelta(seconds=challenge_ttl_seconds)
        db.session.execute(
            text(
                f"""
                UPDATE otp_verifications
                SET    attempt_count = :attempts,
                       verified_at   = NULL,
                       otp_hash      = :otp_hash,
                       expires_at    = :expires_at
                WHERE  {id_pred}
                """
            ),
            {
                "attempts":   attempts,
                "otp_hash":   new_meta,
                "expires_at": _db_dt(exp_dt),
                "otp_id":     otp_id,
            },
        )
        db.session.commit()
        return False, attempts

    store = verification_challenges if purpose == "REGISTER" else password_reset_challenges
    ch = store.get(challenge_id)
    if not ch:
        return True, attempts
    ch["wrong_attempts"] = attempts
    if max_wrong is not None and attempts >= max_wrong:
        store.pop(challenge_id, None)
        return True, attempts
    ch.update(
        {
            "code":       new_code,
            "choices":    list(new_choices),
            "expires_at": time.monotonic() + challenge_ttl_seconds,
        }
    )
    return False, attempts


def mark_registration_verified(challenge_id: str, loaded_challenge: dict[str, Any]) -> None:
    if loaded_challenge["source"] == "db":
        otp_id = loaded_challenge["otp_id"]
        id_pred = "otp_id = CAST(:otp_id AS uuid)" if _is_postgres() else "otp_id = :otp_id"
        now_dt = datetime.now(timezone.utc)
        exp_dt = now_dt + timedelta(seconds=challenge_ttl_seconds)
        db.session.execute(
            text(
                f"""
                UPDATE otp_verifications
                SET    verified_at = :now_dt, expires_at = :expires_at
                WHERE  {id_pred}
                """
            ),
            {"now_dt": _db_dt(now_dt), "expires_at": _db_dt(exp_dt), "otp_id": otp_id},
        )
        db.session.commit()
        return

    ch = verification_challenges.get(challenge_id)
    if ch:
        ch["verified"] = True


def consume_otp_challenge(challenge_id: str, purpose: str) -> None:
    has_otp, _ = has_otp_tables()
    if has_otp:
        parts = _split_challenge_id(challenge_id)
        if parts:
            otp_id, _ = parts
            id_pred = "otp_id = CAST(:otp_id AS uuid)" if _is_postgres() else "otp_id = :otp_id"
            db.session.execute(
                text(f"UPDATE otp_verifications SET consumed_at = :now_dt WHERE {id_pred}"),
                {"now_dt": _db_dt(datetime.now(timezone.utc)), "otp_id": otp_id},
            )
            db.session.commit()
            return
    store = verification_challenges if purpose == "REGISTER" else password_reset_challenges
    store.pop(challenge_id, None)


def issue_password_reset_token(
    challenge_id: str,
    loaded_challenge: dict[str, Any],
    *,
    canonical_role: str | None = None,
    account_id: Any = None,
) -> str:
    if loaded_challenge["source"] == "mem":
        ch = password_reset_challenges[challenge_id]
        if ch.get("verified") and ch.get("reset_token"):
            return ch["reset_token"]
        reset_token = secrets.token_urlsafe(32)
        ch["verified"] = True
        ch["reset_token"] = reset_token
        ch["expires_at"] = time.monotonic() + challenge_ttl_seconds
        return reset_token

    _, has_prt = has_otp_tables()
    reset_token = secrets.token_urlsafe(32)
    rt_sha = _sha256_hex(reset_token)
    otp_id = loaded_challenge["otp_id"]
    is_pg = _is_postgres()
    id_pred = "otp_id = CAST(:otp_id AS uuid)" if is_pg else "otp_id = :otp_id"
    now_dt = datetime.now(timezone.utc)
    exp_dt = now_dt + timedelta(seconds=challenge_ttl_seconds)

    new_meta = json.dumps(
        {
            "secret_sha256": _sha256_hex(loaded_challenge["raw_secret"]),
            "code_hash":     loaded_challenge["code_hash"],
            "choices":       loaded_challenge["choices"],
            "rt_sha256":     rt_sha,
        }
    )
    db.session.execute(
        text(
            f"""
            UPDATE otp_verifications
            SET    verified_at = :now_dt,
                   expires_at  = :expires_at,
                   otp_hash    = :otp_hash
            WHERE  {id_pred}
            """
        ),
        {
            "now_dt":     _db_dt(now_dt),
            "expires_at": _db_dt(exp_dt),
            "otp_hash":   new_meta,
            "otp_id":     otp_id,
        },
    )

    role_db = ROLE_DB_NAMES.get(canonical_role or "", None)
    if has_prt and role_db and account_id is not None:
        # Whitelist-based FK column selection (S2).
        _ROLE_FK: dict[str, str] = {"ADMIN": "admin_id", "LECTURER": "lecturer_id", "STUDENT": "student_id"}
        fk_col = _ROLE_FK[role_db]
        fk_pred = f"{fk_col} = CAST(:acct_id AS uuid)" if is_pg else f"{fk_col} = :acct_id"
        db.session.execute(
            text(
                f"""
                UPDATE password_reset_tokens
                SET    used_at = :now_dt
                WHERE  {fk_pred} AND used_at IS NULL
                """
            ),
            {"now_dt": _db_dt(now_dt), "acct_id": str(account_id) if is_pg else account_id},
        )
        reset_id = str(uuid.uuid4())
        rid_expr = "CAST(:reset_id AS uuid)" if is_pg else ":reset_id"
        aid_expr = "CAST(:admin_id AS uuid)" if is_pg else ":admin_id"
        lid_expr = "CAST(:lecturer_id AS uuid)" if is_pg else ":lecturer_id"
        sid_expr = "CAST(:student_id AS uuid)" if is_pg else ":student_id"
        db.session.execute(
            text(
                f"""
                INSERT INTO password_reset_tokens (
                    reset_id, role_name, admin_id, lecturer_id, student_id,
                    token_hash, expires_at, created_at
                ) VALUES (
                    {rid_expr}, :role_name, {aid_expr}, {lid_expr}, {sid_expr},
                    :token_hash, :expires_at, :created_at
                )
                """
            ),
            {
                "reset_id":    reset_id,
                "role_name":   role_db,
                "admin_id":    str(account_id) if role_db == "ADMIN" and is_pg else (account_id if role_db == "ADMIN" else None),
                "lecturer_id": str(account_id) if role_db == "LECTURER" and is_pg else (account_id if role_db == "LECTURER" else None),
                "student_id":  str(account_id) if role_db == "STUDENT" and is_pg else (account_id if role_db == "STUDENT" else None),
                "token_hash":  rt_sha,
                "expires_at":  _db_dt(exp_dt),
                "created_at":  _db_dt(now_dt),
            },
        )

    db.session.commit()
    return reset_token


def verify_password_reset_session(email: str, challenge_id: str, reset_token: str) -> bool:
    norm_email = email.strip().lower()
    loaded = load_otp_challenge(challenge_id, "RESET_PASSWORD")
    if not loaded or not loaded.get("verified") or loaded["email"] != norm_email:
        return False

    if loaded["source"] == "mem":
        expected = loaded.get("reset_token") or ""
        return bool(expected and secrets.compare_digest(expected, reset_token))

    rt_sha = _sha256_hex(reset_token)
    stored_rt_sha = loaded.get("rt_sha256") or ""
    if not stored_rt_sha or not secrets.compare_digest(stored_rt_sha, rt_sha):
        return False

    _, has_prt = has_otp_tables()
    if has_prt:
        prt_row = db.session.execute(
            text(
                """
                SELECT reset_id, expires_at, used_at
                FROM   password_reset_tokens
                WHERE  token_hash = :token_hash
                """
            ),
            {"token_hash": rt_sha},
        ).mappings().first()
        if not prt_row or prt_row["used_at"] is not None:
            return False
        exp_dt = _parse_db_dt(prt_row["expires_at"])
        if exp_dt is None or datetime.now(timezone.utc) >= exp_dt:
            return False

    return True


def consume_password_reset_session(challenge_id: str, reset_token: str) -> None:
    has_otp, has_prt = has_otp_tables()
    now_dt = datetime.now(timezone.utc)
    if has_prt and reset_token:
        db.session.execute(
            text(
                """
                UPDATE password_reset_tokens
                SET    used_at = :now_dt
                WHERE  token_hash = :token_hash AND used_at IS NULL
                """
            ),
            {"now_dt": _db_dt(now_dt), "token_hash": _sha256_hex(reset_token)},
        )
    if has_otp:
        parts = _split_challenge_id(challenge_id)
        if parts:
            otp_id, _ = parts
            id_pred = "otp_id = CAST(:otp_id AS uuid)" if _is_postgres() else "otp_id = :otp_id"
            db.session.execute(
                text(f"UPDATE otp_verifications SET consumed_at = :now_dt WHERE {id_pred}"),
                {"now_dt": _db_dt(now_dt), "otp_id": otp_id},
            )
        db.session.commit()
        return

    password_reset_challenges.pop(challenge_id, None)


# =====================================================================
# Email validation & SMTP delivery
# =====================================================================

def validate_email_deliverability(email: str) -> str:
    """Validate one address with Abstract API before sending a verification code.

    Fix S7: API key passed via Authorization header only (not in URL query string).
    Fix P5: lazy TTL-only eviction on reads (no full-dict iteration on every call).
    """
    now = time.monotonic()
    cached = email_validation_cache.get(email)
    if cached and now - cached[0] < email_validation_cache_ttl_seconds:
        return cached[1]

    # Lazy eviction: only clean up the looked-up entry if stale (already handled above).
    # Periodic full eviction would be in a background task; skip full scan on every call.

    api_key = (current_app.config.get("EMAIL_VALIDATION_API_KEY") or "").strip()
    if not api_key:
        logger.info("EMAIL_VALIDATION_API_KEY is empty — skipping external AbstractAPI reputation check.")
        return "unknown"

    query = urlencode({"email": email})
    req = Request(
        f"https://emailreputation.abstractapi.com/v1/?{query}",
        # Fix S7: API key ONLY in Authorization header, not in URL.
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )
    try:
        with urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        if error.code == 401:
            code = "email_validation_configuration_error"
        elif error.code in (403, 422):
            code = "email_validation_quota_exceeded"
        elif error.code == 429:
            code = "email_validation_rate_limited"
        else:
            code = "email_validation_unavailable"
        raise EmailValidationServiceError(code) from None
    except (URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError, OSError):
        raise EmailValidationServiceError("email_validation_unavailable") from None

    if not isinstance(result, dict):
        raise EmailValidationServiceError("email_validation_unavailable")

    deliverability_result = result.get("email_deliverability")
    quality_result = result.get("email_quality")
    if not isinstance(deliverability_result, dict):
        return "unknown"
    if not isinstance(quality_result, dict):
        quality_result = {}

    valid_format   = deliverability_result.get("is_format_valid")
    deliverability = deliverability_result.get("status")
    smtp_valid     = deliverability_result.get("is_smtp_valid")
    catchall       = quality_result.get("is_catchall")

    if valid_format is False or deliverability == "undeliverable":
        result_status = "invalid"
    elif deliverability == "deliverable" and smtp_valid is True and catchall is False:
        result_status = "valid"
    else:
        result_status = "unknown"

    email_validation_cache[email] = (now, result_status)
    return result_status


def is_smtp_configured() -> bool:
    smtp_host     = (current_app.config.get("SMTP_HOST") or "").strip()
    smtp_username = (current_app.config.get("SMTP_USERNAME") or "").strip()
    smtp_password = "".join((current_app.config.get("SMTP_PASSWORD") or "").split())
    return bool(smtp_host and smtp_username and smtp_password)


def is_dev_otp_fallback_enabled() -> bool:
    if is_smtp_configured():
        return False
    return os.getenv("SMTP_DEV_CONSOLE_FALLBACK", "0").strip().lower() in ("1", "true", "yes")


def _deliver_smtp_message(message: EmailMessage) -> None:
    smtp_host     = current_app.config["SMTP_HOST"]
    smtp_username = current_app.config["SMTP_USERNAME"]
    smtp_password = "".join((current_app.config["SMTP_PASSWORD"] or "").split())
    smtp_from     = current_app.config["SMTP_FROM"] or smtp_username
    smtp_port     = current_app.config["SMTP_PORT"]

    if not all((smtp_host, smtp_username, smtp_password, smtp_from)):
        if is_dev_otp_fallback_enabled():
            logger.warning(
                "[DEV-OTP] SMTP chưa được điền — bỏ qua gửi thư thật tới %s (%s)",
                message["To"],
                message["Subject"],
            )
            return
        raise RuntimeError("SMTP configuration is incomplete")

    message["From"] = smtp_from
    if smtp_port == 465:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=15, context=ssl.create_default_context()) as smtp:
            smtp.login(smtp_username, smtp_password)
            smtp.send_message(message)
        return

    with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as smtp:
        if current_app.config["SMTP_USE_TLS"]:
            smtp.starttls(context=ssl.create_default_context())
        smtp.login(smtp_username, smtp_password)
        smtp.send_message(message)


def send_verification_email(email: str, code: int) -> None:
    message = EmailMessage()
    message["Subject"] = "Xác thực đăng ký ClassBridge"
    message["To"] = email
    message.set_content(f"Số chọn đăng ký xác thực của bạn là:\n\n{code}")
    message.add_alternative(
        f"""\
        <!doctype html>
        <html lang="vi">
          <body style="margin:0;padding:32px;background:#f4f6fa;font-family:Arial,sans-serif;text-align:center">
            <div style="max-width:480px;margin:0 auto;padding:32px 24px;background:#ffffff;border-radius:12px">
              <p style="margin:0 0 16px;color:#344054;font-size:18px">
                Số chọn đăng ký xác thực của bạn là
              </p>
              <div style="color:#1e1b4b;font-size:48px;font-weight:700;line-height:1.2">
                {code}
              </div>
            </div>
          </body>
        </html>
        """,
        subtype="html",
    )
    _deliver_smtp_message(message)


def send_password_reset_email(email: str, code: int) -> None:
    message = EmailMessage()
    message["Subject"] = "Khôi phục mật khẩu ClassBridge"
    message["To"] = email
    message.set_content(
        f"Số xác thực để đặt lại mật khẩu tài khoản ClassBridge của bạn là:\n\n{code}\n\n"
        "Nếu bạn không yêu cầu đặt lại mật khẩu, hãy bỏ qua email này."
    )
    message.add_alternative(
        f"""\
        <!doctype html>
        <html lang="vi">
          <body style="margin:0;padding:32px;background:#f4f6fa;font-family:Arial,sans-serif;text-align:center">
            <div style="max-width:480px;margin:0 auto;padding:32px 24px;background:#ffffff;border-radius:12px">
              <p style="margin:0 0 12px;color:#344054;font-size:18px;font-weight:600">
                Khôi phục mật khẩu ClassBridge
              </p>
              <p style="margin:0 0 16px;color:#475467;font-size:14px">
                Hãy chọn đúng con số bên dưới trên màn hình khôi phục mật khẩu:
              </p>
              <div style="color:#1e1b4b;font-size:48px;font-weight:700;line-height:1.2">
                {code}
              </div>
              <p style="margin:18px 0 0;color:#98a2b3;font-size:12px">
                Mã có hiệu lực trong 10 phút. Nếu không phải bạn yêu cầu, vui lòng bỏ qua thư này.
              </p>
            </div>
          </body>
        </html>
        """,
        subtype="html",
    )
    _deliver_smtp_message(message)
