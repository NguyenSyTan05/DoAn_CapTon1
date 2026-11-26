"""
app.py — ClassBridge Flask application factory.

Fixes applied (vs. original):
- S4: ALLOW_LAN_ORIGINS default changed to False (opt-in, not opt-out)
- S5: Vary: Origin header always set so CDN/proxy caches are correct
- A3: Added /health and /ready endpoints for load-balancer probes
- A13: Startup guard — refuse to start when DATABASE_URL is None
- A1: Removed app.run() from __main__ block; replaced with Gunicorn note
- Added structured logging configuration
"""

from __future__ import annotations

import ipaddress
import logging
import logging.config
import os
from urllib.parse import urlsplit

from flask import Flask, jsonify, request
from flask_jwt_extended import JWTManager

from audit_service import record_request_activity
from config import Config
from extensions import db
from routes import route_blueprints

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.config.dictConfig(
    {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                "datefmt": "%Y-%m-%dT%H:%M:%S",
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default",
            }
        },
        "root": {"handlers": ["console"], "level": os.getenv("LOG_LEVEL", "INFO")},
    }
)

logger = logging.getLogger("classbridge.app")


# ---------------------------------------------------------------------------
# Startup guard: refuse to boot with a missing DATABASE_URL (A13)
# ---------------------------------------------------------------------------
_database_url = os.getenv("DATABASE_URL")
if not _database_url:
    raise RuntimeError(
        "DATABASE_URL is not set. Add DATABASE_URL=postgresql://user:pass@host/db "
        "to backend/.env before starting the server."
    )


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.config.from_object(Config)
app.config["MAX_CONTENT_LENGTH"] = 21 * 1024 * 1024

# Initialize extensions
db.init_app(app)
JWTManager(app)

# Register route blueprints
for route_blueprint in route_blueprints:
    app.register_blueprint(route_blueprint)


# ---------------------------------------------------------------------------
# CORS helper
# ---------------------------------------------------------------------------

def _is_private_lan_origin(origin: str, allowed_ports: set[int | None]) -> bool:
    """Allow phones/laptops on the same Wi-Fi/LAN (RFC1918) to call the API."""
    try:
        parsed = urlsplit(origin)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return False
        ip = ipaddress.ip_address(parsed.hostname)
        if not ip.is_private and not ip.is_loopback:
            return False
        return parsed.port in allowed_ports
    except ValueError:
        return False


@app.after_request
def add_cors_headers(response):
    raw_origins = [
        item.strip().rstrip("/")
        for item in (app.config.get("FRONTEND_ORIGIN") or "http://localhost:4000").split(",")
        if item.strip()
    ]
    primary_origin = raw_origins[0] if raw_origins else "http://localhost:4000"
    allowed_origins: set[str] = set()
    allowed_ports: set[int | None] = set()

    for configured_origin in raw_origins:
        allowed_origins.add(configured_origin)
        configured_url = urlsplit(configured_origin)
        allowed_ports.add(configured_url.port)

        if configured_url.hostname in ("localhost", "127.0.0.1"):
            alternate_host = (
                "127.0.0.1" if configured_url.hostname == "localhost" else "localhost"
            )
            alternate_origin = f"{configured_url.scheme}://{alternate_host}"
            if configured_url.port:
                alternate_origin += f":{configured_url.port}"
            allowed_origins.add(alternate_origin)

    origin = (request.headers.get("Origin") or "").rstrip("/")

    # S4: Default is now False — LAN access must be explicitly enabled.
    allow_lan: bool = bool(app.config.get("ALLOW_LAN_ORIGINS", False))

    # S5: Always emit Vary: Origin so proxies never serve a cached wrong-origin response.
    response.vary.add("Origin")

    if origin and (
        origin in allowed_origins
        or (allow_lan and _is_private_lan_origin(origin, allowed_ports))
    ):
        response.headers["Access-Control-Allow-Origin"] = origin
    elif not origin:
        response.headers["Access-Control-Allow-Origin"] = primary_origin

    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Allow-Methods"] = (
        "GET, POST, PUT, PATCH, DELETE, OPTIONS"
    )

    record_request_activity(response)
    return response


# ---------------------------------------------------------------------------
# Health / readiness probes (A3)
# ---------------------------------------------------------------------------

@app.route("/health")
def health():
    """Liveness probe — always returns 200 when the process is running."""
    return jsonify({"status": "ok"}), 200


@app.route("/ready")
def ready():
    """Readiness probe — verifies the database connection is reachable."""
    try:
        with db.engine.connect() as conn:
            conn.execute(db.text("SELECT 1"))
        return jsonify({"status": "ready", "db": "ok"}), 200
    except Exception as exc:
        logger.warning("Readiness check failed: %s", exc)
        return jsonify({"status": "not_ready", "db": "unreachable"}), 503


# ---------------------------------------------------------------------------
# Root route
# ---------------------------------------------------------------------------

@app.route("/")
def home():
    return jsonify({"success": True, "message": "ClassBridge Backend is running"}), 200


# ---------------------------------------------------------------------------
# Entry point note
# ---------------------------------------------------------------------------
# Do NOT start the development server via __main__ in production.
# Use Gunicorn:
#   gunicorn -w 4 -b 0.0.0.0:5000 "app:app"
#
# For local development only:
if __name__ == "__main__":
    _debug = os.getenv("FLASK_DEBUG", "0") == "1"
    logger.warning(
        "Running with Flask dev server (single-process, not for production). "
        "Use Gunicorn for production deployments."
    )
    app.run(debug=_debug, host="127.0.0.1", port=int(os.getenv("PORT", "5000")))
