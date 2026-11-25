"""Closed sessions (ENDED / CANCELLED):

* GET /auth/sessions/<id>/access (routes/session_access.py) -> 403 session_closed for
  lecturer/student members, admin still 200, unrelated users still session_forbidden.
* GET /auth/student/sessions/<id> and POST .../join (routes/student_classes.py)
  -> 403 session_closed; SCHEDULED join -> 409 "Buổi học chưa diễn ra.".

student_classes.py uses PostgreSQL-only SQL (``x::text``, ``CAST(:p AS uuid)``,
``NOW()``). The ``pg_sql_on_sqlite`` fixture rewrites only those constructs on
the way to SQLite (test-only shim, app code untouched), so the route logic and
the membership/class-status WHERE clauses run for real; the PostgreSQL syntax
itself is not verified here.
"""
import re

import pytest
from sqlalchemy import event, text
from werkzeug.security import generate_password_hash

from conftest import PASSWORD
from extensions import db

LIVE_SID = "a1111111-1111-1111-1111-111111111111"
ENDED_SID = "a2222222-2222-2222-2222-222222222222"
CANCELLED_SID = "a3333333-3333-3333-3333-333333333333"
SCHEDULED_SID = "a4444444-4444-4444-4444-444444444444"
ENDED_LOWER_SID = "a5555555-5555-5555-5555-555555555555"
CANCELLED_LOWER_SID = "a6666666-6666-6666-6666-666666666666"
OTHER_ENDED_SID = "a7777777-7777-7777-7777-777777777777"  # class c2 (other lecturer, no members)

CLOSED_SIDS = [ENDED_SID, CANCELLED_SID, ENDED_LOWER_SID, CANCELLED_LOWER_SID]

CLOSED_MSG = "Phiên học đã kết thúc hoặc bị huỷ."
NOT_FOUND_MSG = "Không tìm thấy phiên học hoặc bạn chưa tham gia lớp này."


@pytest.fixture()
def seeded(app):
    h = generate_password_hash(PASSWORD)
    with app.app_context():
        db.session.execute(text("INSERT INTO lecturers VALUES (2,'GV Other','gv2@example.com',:h,1)"), {"h": h})
        db.session.execute(text("INSERT INTO students VALUES (3,'SV Outsider','sv3@example.com',:h,1)"), {"h": h})
        stmts = [
            "INSERT INTO classes VALUES ('c1', 1, 'C1', 'Lop 1', 'ACTIVE')",
            "INSERT INTO classes VALUES ('c2', 2, 'C2', 'Lop 2', 'ACTIVE')",
            "INSERT INTO class_members (class_id, student_id, status) VALUES ('c1', 1, 'ACTIVE')",
        ]
        for i, (sid, status, cls) in enumerate([
            (LIVE_SID, "LIVE", "c1"),
            (ENDED_SID, "ENDED", "c1"),
            (CANCELLED_SID, "CANCELLED", "c1"),
            (SCHEDULED_SID, "SCHEDULED", "c1"),
            (ENDED_LOWER_SID, "ended", "c1"),
            (CANCELLED_LOWER_SID, "Cancelled", "c1"),
            (OTHER_ENDED_SID, "ENDED", "c2"),
        ]):
            stmts.append(
                f"INSERT INTO sessions (session_id, class_id, status, join_code) "
                f"VALUES ('{sid}', '{cls}', '{status}', 'JC{i}')"
            )
        for stmt in stmts:
            db.session.execute(text(stmt))
        db.session.commit()
    return app


# =====================================================================
# /auth/sessions/<id>/access
# =====================================================================

def get_access(client, sid, headers):
    return client.get(f"/auth/sessions/{sid}/access", headers=headers)


@pytest.mark.parametrize("sid", CLOSED_SIDS)
@pytest.mark.parametrize("role,email", [
    ("giang_vien", "gv@example.com"),
    ("sinh_vien", "sv@example.com"),
    ("student", "sv@example.com"),  # legacy student role value
])
def test_access_closed_session_member_403_session_closed(client, make_token, seeded, sid, role, email):
    r = get_access(client, sid, make_token(role, email))
    assert r.status_code == 403
    assert r.get_json() == {"code": "session_closed"}


@pytest.mark.parametrize("sid", CLOSED_SIDS + [OTHER_ENDED_SID])
def test_access_closed_session_admin_still_200(client, make_token, seeded, sid):
    r = get_access(client, sid, make_token("admin", "admin@example.com"))
    assert r.status_code == 200
    assert r.get_json() == {"session_id": sid, "role": "admin", "access": "admin"}


@pytest.mark.parametrize("role,email,sid", [
    ("giang_vien", "gv2@example.com", ENDED_SID),       # lecturer of another class
    ("giang_vien", "gv@example.com", OTHER_ENDED_SID),  # own lecturer, other class's session
    ("sinh_vien", "sv3@example.com", ENDED_SID),        # student not in class
    ("sinh_vien", "sv3@example.com", CANCELLED_SID),
    ("sinh_vien", "nobody@example.com", ENDED_LOWER_SID),
    ("hacker", "sv@example.com", ENDED_SID),            # unknown role
])
def test_access_closed_session_unrelated_user_session_forbidden(client, make_token, seeded, role, email, sid):
    # membership is checked first: outsiders never learn the session is closed
    r = get_access(client, sid, make_token(role, email))
    assert r.status_code == 403
    assert r.get_json() == {"code": "session_forbidden"}


@pytest.mark.parametrize("sid", [LIVE_SID, SCHEDULED_SID])
@pytest.mark.parametrize("role,email,access", [
    ("giang_vien", "gv@example.com", "lecturer"),
    ("sinh_vien", "sv@example.com", "student"),
])
def test_access_open_session_still_200(client, make_token, seeded, sid, role, email, access):
    r = get_access(client, sid, make_token(role, email))
    assert r.status_code == 200
    assert r.get_json()["access"] == access


def test_access_closed_uppercase_id_still_closed(client, make_token, seeded):
    r = get_access(client, ENDED_SID.upper(), make_token("sinh_vien", "sv@example.com"))
    assert r.status_code == 403
    assert r.get_json() == {"code": "session_closed"}


# =====================================================================
# /auth/student/sessions/<id> and /join (student_classes.py)
# =====================================================================

_PG_TEXT_CAST = re.compile(r"([A-Za-z_][\w.]*)::text")
# at cursor level parameters are already positional ("?")
_PG_UUID_CAST = re.compile(r"CAST\((\?|:\w+) AS uuid\)", re.IGNORECASE)


@pytest.fixture()
def pg_sql_on_sqlite(seeded):
    """Rewrite the PostgreSQL-only bits of student_classes.py SQL for SQLite."""
    seen = []

    def rewrite(conn, cursor, statement, parameters, context, executemany):
        new = _PG_TEXT_CAST.sub(r"CAST(\1 AS TEXT)", statement)
        new = _PG_UUID_CAST.sub(r"\1", new)
        new = new.replace("NOW()", "CURRENT_TIMESTAMP")
        seen.append(new)
        return new, parameters

    with seeded.app_context():
        engine = db.engine
    event.listen(engine, "before_cursor_execute", rewrite, retval=True)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", rewrite)


def student_sessions_rows(app):
    with app.app_context():
        return db.session.execute(
            text("SELECT student_id, session_id, is_active FROM student_sessions")
        ).all()


SV = ("sinh_vien", "sv@example.com")


# ---- GET session -------------------------------------------------------

def test_get_live_session_200(client, make_token, pg_sql_on_sqlite):
    r = client.get(f"/auth/student/sessions/{LIVE_SID}", headers=make_token(*SV))
    assert r.status_code == 200, r.get_json()
    body = r.get_json()["session"]
    assert body["id"] == LIVE_SID and body["status"] == "LIVE"
    assert body["class"] == {"id": "c1", "code": "C1", "name": "Lop 1"}
    assert body["lecturerName"] == "GV Test"


def test_get_scheduled_session_200(client, make_token, pg_sql_on_sqlite):
    r = client.get(f"/auth/student/sessions/{SCHEDULED_SID}", headers=make_token(*SV))
    assert r.status_code == 200
    assert r.get_json()["session"]["status"] == "SCHEDULED"


@pytest.mark.parametrize("sid", CLOSED_SIDS)
@pytest.mark.parametrize("role", ["sinh_vien", "student"])
def test_get_closed_session_403_session_closed(client, make_token, pg_sql_on_sqlite, sid, role):
    r = client.get(f"/auth/student/sessions/{sid}", headers=make_token(role, "sv@example.com"))
    assert r.status_code == 403
    assert r.get_json() == {"message": CLOSED_MSG, "code": "session_closed"}


@pytest.mark.parametrize("email,sid", [
    ("sv3@example.com", ENDED_SID),  # not a member: 404, closed state not revealed
    ("sv@example.com", OTHER_ENDED_SID),
])
def test_get_closed_session_non_member_404(client, make_token, pg_sql_on_sqlite, email, sid):
    r = client.get(f"/auth/student/sessions/{sid}", headers=make_token("sinh_vien", email))
    assert r.status_code == 404
    assert r.get_json() == {"message": NOT_FOUND_MSG}


@pytest.mark.parametrize("role", ["giang_vien", "admin"])
def test_get_session_wrong_role_403(client, make_token, pg_sql_on_sqlite, role):
    r = client.get(f"/auth/student/sessions/{ENDED_SID}", headers=make_token(role, "gv@example.com"))
    assert r.status_code == 403
    assert r.get_json()["code"] == "role_forbidden"


def test_get_session_bad_id_400(client, make_token, pg_sql_on_sqlite):
    r = client.get("/auth/student/sessions/not-a-uuid", headers=make_token(*SV))
    assert r.status_code == 400


def test_get_session_no_token_401(client, pg_sql_on_sqlite):
    assert client.get(f"/auth/student/sessions/{ENDED_SID}").status_code == 401


# ---- POST join -----------------------------------------------------------

@pytest.mark.parametrize("sid", CLOSED_SIDS)
def test_join_closed_session_403_session_closed(client, make_token, seeded, pg_sql_on_sqlite, sid):
    r = client.post(f"/auth/student/sessions/{sid}/join", headers=make_token(*SV))
    assert r.status_code == 403
    assert r.get_json() == {"message": CLOSED_MSG, "code": "session_closed"}
    assert student_sessions_rows(seeded) == []  # no attendance written


def test_join_scheduled_session_409(client, make_token, seeded, pg_sql_on_sqlite):
    r = client.post(f"/auth/student/sessions/{SCHEDULED_SID}/join", headers=make_token(*SV))
    assert r.status_code == 409
    body = r.get_json()
    assert body["message"] == "Buổi học chưa diễn ra."
    assert body["session"]["id"] == SCHEDULED_SID and body["session"]["status"] == "SCHEDULED"
    assert "code" not in body
    assert student_sessions_rows(seeded) == []


def test_join_live_session_200_and_idempotent(client, make_token, seeded, pg_sql_on_sqlite):
    for _ in range(2):
        r = client.post(f"/auth/student/sessions/{LIVE_SID}/join", headers=make_token(*SV))
        assert r.status_code == 200, r.get_json()
        assert r.get_json()["success"] is True
    rows = student_sessions_rows(seeded)
    assert len(rows) == 1
    assert rows[0][1] == LIVE_SID and rows[0][2] is True


def test_join_closed_session_non_member_404(client, make_token, seeded, pg_sql_on_sqlite):
    r = client.post(f"/auth/student/sessions/{ENDED_SID}/join", headers=make_token("sinh_vien", "sv3@example.com"))
    assert r.status_code == 404
    assert r.get_json() == {"message": NOT_FOUND_MSG}


@pytest.mark.parametrize("role", ["giang_vien", "admin"])
def test_join_wrong_role_403(client, make_token, pg_sql_on_sqlite, role):
    r = client.post(f"/auth/student/sessions/{LIVE_SID}/join", headers=make_token(role, "gv@example.com"))
    assert r.status_code == 403
    assert r.get_json()["code"] == "role_forbidden"


def test_join_inactive_student_403(client, make_token, pg_sql_on_sqlite):
    r = client.post(f"/auth/student/sessions/{LIVE_SID}/join", headers=make_token("sinh_vien", "off@example.com"))
    assert r.status_code == 403
