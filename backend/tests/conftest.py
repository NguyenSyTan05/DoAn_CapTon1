"""Pytest setup for the Flask backend.

Environment is forced BEFORE the app is imported so tests never reach the
shared Neon database: DATABASE_URL points to in-memory SQLite and SECRET_KEY is a
throwaway test value. Mail/validation settings are cleared.
"""
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

TEST_SECRET_KEY = "test-secret-key-0123456789-abcdefghijklmnop"
os.environ["SECRET_KEY"] = TEST_SECRET_KEY
os.environ["DATABASE_URL"] = "sqlite://"  # in-memory, never Neon
os.environ["FRONTEND_ORIGIN"] = "http://localhost:4000"
for _name in ("SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM", "EMAIL_VALIDATION_API_KEY"):
    os.environ.pop(_name, None)

import functools  # noqa: E402
import sqlite3  # noqa: E402

# SQLite returns BOOLEAN columns as 0/1, but routes check `is_active is not True`
# (true on PostgreSQL). Convert BOOLEAN declared columns to real bools.
sqlite3.register_converter("BOOLEAN", lambda raw: raw not in (b"0", b""))
_connect = functools.partial(sqlite3.connect, detect_types=sqlite3.PARSE_DECLTYPES)
sqlite3.connect = _connect
sqlite3.dbapi2.connect = _connect  # SQLAlchemy's pysqlite dialect uses dbapi2

import pytest  # noqa: E402
from flask_jwt_extended import create_access_token  # noqa: E402
from sqlalchemy import text  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402

import app as app_module  # noqa: E402
from extensions import db  # noqa: E402
import request_limits  # noqa: E402

assert app_module.app.config["SQLALCHEMY_DATABASE_URI"] == "sqlite://", "tests must use SQLite"

SCHEMA = [
    """CREATE TABLE students (student_id INTEGER PRIMARY KEY, full_name TEXT, email TEXT,
       password_hash TEXT, is_active BOOLEAN)""",
    """CREATE TABLE lecturers (lecturer_id INTEGER PRIMARY KEY, full_name TEXT, email TEXT,
       password_hash TEXT, is_active BOOLEAN)""",
    """CREATE TABLE admins (admin_id INTEGER PRIMARY KEY, full_name TEXT, email TEXT,
       password_hash TEXT, is_active BOOLEAN)""",
    # Subset of db.sql columns used by /auth/sessions/<id>/access.
    """CREATE TABLE classes (class_id TEXT PRIMARY KEY, lecturer_id INTEGER NOT NULL,
       class_code TEXT NOT NULL UNIQUE, class_name TEXT NOT NULL,
       status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','INACTIVE','ARCHIVED')))""",
    """CREATE TABLE class_members (class_member_id INTEGER PRIMARY KEY, class_id TEXT NOT NULL,
       student_id INTEGER NOT NULL,
       status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','INACTIVE','REMOVED')),
       UNIQUE (class_id, student_id))""",
    # status has no CHECK here on purpose (tests probe lower-case values).
    """CREATE TABLE sessions (session_id TEXT PRIMARY KEY, class_id TEXT NOT NULL,
       session_title TEXT NOT NULL DEFAULT 'Buoi hoc',
       status TEXT NOT NULL DEFAULT 'SCHEDULED', join_code TEXT NOT NULL UNIQUE,
       started_at TEXT, ended_at TEXT, delivery_mode TEXT)""",
    # Subset of db.sql student_sessions used by /auth/student/sessions/<id>/join|leave.
    """CREATE TABLE student_sessions (student_session_id INTEGER PRIMARY KEY, student_id INTEGER,
       session_id TEXT NOT NULL, joined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
       last_active_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, left_at TEXT,
       is_active BOOLEAN NOT NULL DEFAULT 1, UNIQUE (student_id, session_id))""",
]
TABLES = ("students", "lecturers", "admins", "classes", "class_members", "sessions", "student_sessions")

PASSWORD = "Correct-Pass-1"


@pytest.fixture()
def app():
    flask_app = app_module.app
    flask_app.config["TESTING"] = True
    with flask_app.app_context():
        for stmt in SCHEMA:
            db.session.execute(text(stmt))
        h = generate_password_hash(PASSWORD)
        db.session.execute(text("INSERT INTO students VALUES (1,'SV Test','sv@example.com',:h,1)"), {"h": h})
        db.session.execute(text("INSERT INTO lecturers VALUES (1,'GV Test','gv@example.com',:h,1)"), {"h": h})
        db.session.execute(text("INSERT INTO admins VALUES (1,'Admin Test','admin@example.com',:h,1)"), {"h": h})
        db.session.execute(text("INSERT INTO students VALUES (2,'SV Off','off@example.com',:h,0)"), {"h": h})
        db.session.commit()
        request_limits._events.clear()
        yield flask_app
        db.session.remove()
        for t in TABLES:
            db.session.execute(text(f"DROP TABLE IF EXISTS {t}"))
        db.session.commit()
        request_limits._events.clear()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def make_token(app):
    def _make(role, email="someone@example.com"):
        with app.app_context():
            return {"Authorization": "Bearer " + create_access_token(identity=email, additional_claims={"role": role})}
    return _make
