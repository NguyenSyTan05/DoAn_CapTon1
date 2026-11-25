"""Role protection: no token -> 401, wrong role -> 403.

The denials happen before any business query, so no seeded data is needed.
"""
import pytest

ADMIN_ENDPOINTS = [
    ("GET", "/auth/admin/classes"),
    ("POST", "/auth/admin/classes"),
]
LECTURER_ENDPOINTS = [
    ("GET", "/giang-vien/dashboard"),
]
STUDENT_ENDPOINTS = [
    ("GET", "/auth/student/classes"),
    ("POST", "/auth/student/classes/join"),
]


def call(client, method, url, headers=None):
    return client.open(url, method=method, headers=headers or {}, json={"code": "ABC123"} if method == "POST" else None)


@pytest.mark.parametrize("method,url", ADMIN_ENDPOINTS + LECTURER_ENDPOINTS + STUDENT_ENDPOINTS)
def test_no_token_401(client, method, url):
    assert call(client, method, url).status_code == 401


@pytest.mark.parametrize("role", ["sinh_vien", "giang_vien"])
@pytest.mark.parametrize("method,url", ADMIN_ENDPOINTS)
def test_admin_endpoints_reject_other_roles(client, make_token, role, method, url):
    assert call(client, method, url, make_token(role)).status_code == 403


@pytest.mark.parametrize("role", ["sinh_vien", "admin"])
@pytest.mark.parametrize("method,url", LECTURER_ENDPOINTS)
def test_lecturer_endpoints_reject_other_roles(client, make_token, role, method, url):
    assert call(client, method, url, make_token(role)).status_code == 403


@pytest.mark.parametrize("role", ["giang_vien", "admin"])
@pytest.mark.parametrize("method,url", STUDENT_ENDPOINTS)
def test_student_endpoints_reject_other_roles(client, make_token, role, method, url):
    assert call(client, method, url, make_token(role)).status_code in (401, 403)


def test_garbage_token_rejected(client):
    r = call(client, "GET", "/auth/admin/classes", {"Authorization": "Bearer not.a.jwt"})
    assert r.status_code in (401, 422)
