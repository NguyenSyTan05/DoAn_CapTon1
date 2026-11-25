from conftest import PASSWORD


def post(client, body):
    return client.post("/auth/login", json=body)


def test_success_returns_token_and_role(client):
    r = post(client, {"email": "gv@example.com", "password": PASSWORD})
    assert r.status_code == 200
    data = r.get_json()
    assert data["access_token"]
    assert data["user"]["role"] == "giang_vien"


def test_email_case_insensitive(client):
    r = post(client, {"email": "ADMIN@Example.com", "password": PASSWORD})
    assert r.status_code == 200
    assert r.get_json()["user"]["role"] == "admin"


def test_wrong_password_401(client):
    r = post(client, {"email": "sv@example.com", "password": "nope"})
    assert r.status_code == 401
    assert r.get_json()["code"] == "password_incorrect"
    assert "access_token" not in r.get_json()


def test_unknown_email_404(client):
    r = post(client, {"email": "nobody@example.com", "password": PASSWORD})
    assert r.status_code == 404


def test_disabled_account_403(client):
    r = post(client, {"email": "off@example.com", "password": PASSWORD})
    assert r.status_code == 403


def test_missing_email_400(client):
    assert post(client, {"password": PASSWORD}).status_code == 400


def test_missing_password_400(client):
    assert post(client, {"email": "sv@example.com"}).status_code == 400


def test_empty_body_400(client):
    assert post(client, {}).status_code == 400


def test_non_json_body_400(client):
    r = client.post("/auth/login", data="email=a", content_type="text/plain")
    assert r.status_code == 400


def test_invalid_email_format_400(client):
    r = post(client, {"email": "not-an-email", "password": PASSWORD})
    assert r.status_code == 400
    assert r.get_json()["code"] == "invalid_email"


def test_password_too_long_400(client):
    r = post(client, {"email": "sv@example.com", "password": "a" * 65})
    assert r.status_code == 400


def test_non_string_password_400(client):
    assert post(client, {"email": "sv@example.com", "password": 12345}).status_code == 400


def test_rate_limit_after_10_attempts(client):
    for _ in range(10):
        post(client, {"email": "sv@example.com", "password": "bad"})
    assert post(client, {"email": "sv@example.com", "password": "bad"}).status_code == 429
