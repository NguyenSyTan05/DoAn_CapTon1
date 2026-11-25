"""GET /auth/sessions/<session_id>/access (called by ai-service) and related
role-auth phase 1 behaviour: role_forbidden 403 body, per-role token lifetime.
"""
import jwt
import pytest
from sqlalchemy import text
from werkzeug.security import generate_password_hash

from conftest import PASSWORD, TEST_SECRET_KEY
from extensions import db

SID = "11111111-1111-1111-1111-111111111111"          # class c1, lecturer 1, student 1 member
OTHER_SID = "22222222-2222-2222-2222-222222222222"    # class c2, other lecturer, no members
ARCHIVED_SID = "33333333-3333-3333-3333-333333333333"  # class c3 ARCHIVED, lecturer 1, student 1 member
UNKNOWN_SID = "44444444-4444-4444-4444-444444444444"


@pytest.fixture()
def seeded(app):
    h = generate_password_hash(PASSWORD)
    with app.app_context():
        db.session.execute(text("INSERT INTO lecturers VALUES (2,'GV Other','gv2@example.com',:h,1)"), {"h": h})
        db.session.execute(text("INSERT INTO lecturers VALUES (3,'GV Off','gvoff@example.com',:h,0)"), {"h": h})
        db.session.execute(text("INSERT INTO admins VALUES (2,'Admin Off','adminoff@example.com',:h,0)"), {"h": h})
        db.session.execute(text("INSERT INTO students VALUES (3,'SV Outsider','sv3@example.com',:h,1)"), {"h": h})
        db.session.execute(text("INSERT INTO students VALUES (4,'SV Removed','sv4@example.com',:h,1)"), {"h": h})
        for stmt in (
            "INSERT INTO classes VALUES ('c1', 1, 'C1', 'Lop 1', 'ACTIVE')",
            "INSERT INTO classes VALUES ('c2', 2, 'C2', 'Lop 2', 'ACTIVE')",
            "INSERT INTO classes VALUES ('c3', 1, 'C3', 'Lop 3', 'ARCHIVED')",
            "INSERT INTO classes VALUES ('c4', 3, 'C4', 'Lop 4', 'ACTIVE')",
            f"INSERT INTO sessions (session_id, class_id, join_code) VALUES ('{SID}', 'c1', 'J1')",
            f"INSERT INTO sessions (session_id, class_id, join_code) VALUES ('{OTHER_SID}', 'c2', 'J2')",
            f"INSERT INTO sessions (session_id, class_id, join_code) VALUES ('{ARCHIVED_SID}', 'c3', 'J3')",
            "INSERT INTO sessions (session_id, class_id, join_code) "
            "VALUES ('55555555-5555-5555-5555-555555555555', 'c4', 'J4')",
            "INSERT INTO class_members (class_id, student_id, status) VALUES ('c1', 1, 'ACTIVE')",
            "INSERT INTO class_members (class_id, student_id, status) VALUES ('c1', 2, 'ACTIVE')",  # inactive acct
            "INSERT INTO class_members (class_id, student_id, status) VALUES ('c1', 4, 'REMOVED')",
            "INSERT INTO class_members (class_id, student_id, status) VALUES ('c3', 1, 'ACTIVE')",
        ):
            db.session.execute(text(stmt))
        db.session.commit()
    return app


def get_access(client, sid, headers=None):
    return client.get(f"/auth/sessions/{sid}/access", headers=headers or {})


# ---- 200 ----------------------------------------------------------------

@pytest.mark.parametrize("role,email,access", [
    ("giang_vien", "gv@example.com", "lecturer"),
    ("sinh_vien", "sv@example.com", "student"),
    ("student", "sv@example.com", "student"),  # legacy role value
    ("admin", "admin@example.com", "admin"),
])
def test_access_ok_per_role(client, make_token, seeded, role, email, access):
    r = get_access(client, SID, make_token(role, email))
    assert r.status_code == 200
    assert r.get_json() == {"session_id": SID, "role": role, "access": access}


def test_email_case_insensitive(client, make_token, seeded):
    r = get_access(client, SID, make_token("giang_vien", "GV@Example.COM"))
    assert r.status_code == 200
    assert r.get_json()["access"] == "lecturer"


def test_admin_can_observe_any_session(client, make_token, seeded):
    r = get_access(client, OTHER_SID, make_token("admin", "admin@example.com"))
    assert r.status_code == 200
    assert r.get_json()["access"] == "admin"


def test_uppercase_uuid_is_normalized(client, make_token, seeded):
    r = get_access(client, SID.upper(), make_token("sinh_vien", "sv@example.com"))
    assert r.status_code == 200
    assert r.get_json()["session_id"] == SID


# ---- 400 / 401 / 404 ----------------------------------------------------

@pytest.mark.parametrize("bad", ["abc", "not-a-uuid", "1234", "11111111-1111-1111-1111-11111111111Z"])
def test_non_uuid_400(client, make_token, seeded, bad):
    r = get_access(client, bad, make_token("sinh_vien", "sv@example.com"))
    assert r.status_code == 400
    assert r.get_json() == {"code": "invalid_session_id"}


def test_no_token_401(client, seeded):
    assert get_access(client, SID).status_code == 401


def test_bad_signature_401_or_422(client, seeded):
    forged = jwt.encode({"sub": "gv@example.com", "role": "giang_vien", "type": "access"},
                        "x" * 40, algorithm="HS256")
    r = get_access(client, SID, {"Authorization": "Bearer " + forged})
    assert r.status_code in (401, 422)


def test_unknown_session_404(client, make_token, seeded):
    r = get_access(client, UNKNOWN_SID, make_token("sinh_vien", "sv@example.com"))
    assert r.status_code == 404
    assert r.get_json() == {"code": "session_not_found"}


# ---- 403 ----------------------------------------------------------------

FORBIDDEN_CASES = [
    # unrelated users
    ("giang_vien", "gv@example.com", OTHER_SID),       # lecturer of another class
    ("giang_vien", "gv2@example.com", SID),
    ("sinh_vien", "sv3@example.com", SID),             # student not in class
    ("sinh_vien", "sv4@example.com", SID),             # membership REMOVED
    ("sinh_vien", "nobody@example.com", SID),          # no account at all
    # inactive accounts
    ("sinh_vien", "off@example.com", SID),             # member but account disabled
    ("giang_vien", "gvoff@example.com", "55555555-5555-5555-5555-555555555555"),
    ("admin", "adminoff@example.com", SID),
    ("admin", "nobody@example.com", SID),
    # archived class
    ("giang_vien", "gv@example.com", ARCHIVED_SID),
    ("sinh_vien", "sv@example.com", ARCHIVED_SID),
    # unknown role / role-email mismatch
    ("hacker", "sv@example.com", SID),
    ("giang_vien", "sv@example.com", SID),
]


@pytest.mark.parametrize("role,email,sid", FORBIDDEN_CASES)
def test_forbidden_403(client, make_token, seeded, role, email, sid):
    r = get_access(client, sid, make_token(role, email))
    assert r.status_code == 403
    assert r.get_json() == {"code": "session_forbidden"}


# ---- 503 ----------------------------------------------------------------

def test_db_error_503(client, make_token, app):
    # Tables missing -> SQLAlchemyError -> 503, never 500.
    with app.app_context():
        db.session.execute(text("DROP TABLE sessions"))
        db.session.commit()
    r = get_access(client, SID, make_token("sinh_vien", "sv@example.com"))
    assert r.status_code == 503
    assert r.get_json() == {"code": "session_access_unavailable"}


# ---- role_forbidden body on migrated routes -------------------------------

ADMIN_MSG = "Administrator access is required."
LECTURER_MSG = "Không tìm thấy tài khoản giảng viên."


@pytest.mark.parametrize("method,url", [
    ("GET", "/auth/admin/classes"),
    ("GET", "/auth/admin/accounts"),
    ("GET", "/auth/admin/logs"),
])
@pytest.mark.parametrize("role", ["sinh_vien", "giang_vien"])
def test_admin_route_role_forbidden_body(client, make_token, method, url, role):
    r = client.open(url, method=method, headers=make_token(role))
    assert r.status_code == 403
    assert r.get_json() == {"message": ADMIN_MSG, "code": "role_forbidden"}


@pytest.mark.parametrize("method,url", [
    ("GET", "/giang-vien/dashboard"),
    ("GET", "/auth/lecturer/classes"),
])
@pytest.mark.parametrize("role", ["sinh_vien", "admin"])
def test_lecturer_route_role_forbidden_body(client, make_token, method, url, role):
    r = client.open(url, method=method, headers=make_token(role))
    assert r.status_code == 403
    assert r.get_json() == {"message": LECTURER_MSG, "code": "role_forbidden"}


def test_role_required_still_401_without_token(client):
    assert client.get("/auth/admin/accounts").status_code == 401
    assert client.get("/auth/lecturer/classes").status_code == 401


def test_options_preflight_not_blocked(client):
    assert client.options("/auth/admin/classes").status_code in (200, 204)


# ---- per-role token lifetime --------------------------------------------

@pytest.mark.parametrize("email,role,hours", [
    ("admin@example.com", "admin", 1),
    ("gv@example.com", "giang_vien", 8),
    ("sv@example.com", "sinh_vien", 4),
])
def test_token_lifetime_per_role(client, email, role, hours):
    r = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200
    claims = jwt.decode(r.get_json()["access_token"], TEST_SECRET_KEY, algorithms=["HS256"])
    assert claims["exp"] - claims["iat"] == hours * 3600
    assert claims["sub"] == email
    assert claims["role"] == role
    assert claims["type"] == "access"
