"""
email_utils.py — Email format validation for ClassBridge backend.

Provides:
  - is_valid_email_format(email): RFC5322-compatible lightweight regex check.
    Returns True when the string looks like a valid email address.
    Does NOT perform deliverability or DNS checks (use validation_service for that).
"""

from __future__ import annotations

import re

# RFC5322-simplified pattern used throughout the backend.
# Covers the vast majority of real-world addresses without false positives.
_EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$",
    re.IGNORECASE,
)

_MAX_EMAIL_LENGTH = 255


def is_valid_email_format(email: object) -> bool:
    """Return True if *email* is a non-empty string that looks like a valid address.

    This is a pure-syntax check (no network, no DNS lookup).

    Args:
        email: Arbitrary input from request payload.

    Returns:
        bool: True when the format is acceptable, False otherwise.
    """
    if not isinstance(email, str):
        return False
    email = email.strip()
    if not email or len(email) > _MAX_EMAIL_LENGTH:
        return False
    return bool(_EMAIL_RE.fullmatch(email))
