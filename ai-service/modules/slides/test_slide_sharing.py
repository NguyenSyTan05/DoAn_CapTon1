"""
Tests cho chia sẻ slide: giảng viên upload PDF theo phiên, sinh viên tải về và theo số trang
qua /api/v1/ws/slides. (Nội dung PDF là giả — chỉ kiểm tra lưu/phát, không render.)
"""

from __future__ import annotations

from urllib.parse import quote

PDF = b"%PDF-1.4\n% test deck\n"
HEAD = {"Content-Type": "application/pdf", "X-Filename": quote("Bài giảng 1.pdf")}


def test_upload_download_and_state(api_client):
    r = api_client.post("/api/v1/slides/file?session=deck-1", content=PDF, headers=HEAD)
    assert r.status_code == 200
    body = r.json()
    assert body["has_file"] and body["filename"] == "Bài giảng 1.pdf" and body["version"] == 1 and body["page"] == 1

    got = api_client.get("/api/v1/slides/file?session=deck-1")
    assert got.status_code == 200 and got.content == PDF
    assert got.headers["content-type"] == "application/pdf"

    # upload lại -> version tăng
    again = api_client.post("/api/v1/slides/file?session=deck-1", content=PDF + b"x", headers=HEAD).json()
    assert again["version"] == 2


def test_sessions_are_isolated(api_client):
    api_client.post("/api/v1/slides/file?session=deck-a", content=PDF, headers=HEAD)
    assert api_client.get("/api/v1/slides/file?session=deck-a").status_code == 200
    assert api_client.get("/api/v1/slides/file?session=deck-b").status_code == 404
    assert api_client.get("/api/v1/slides/state?session=deck-b").json()["has_file"] is False


def test_rejects_non_pdf_and_oversize(api_client):
    bad = api_client.post("/api/v1/slides/file?session=deck-x", content=b"not a pdf", headers=HEAD)
    assert bad.status_code == 415
    big = api_client.post(
        "/api/v1/slides/file?session=deck-x", content=b"%PDF-" + b"0" * (20 * 1024 * 1024), headers=HEAD
    )
    assert big.status_code == 413


def test_ws_receives_state_upload_and_page(api_client):
    with api_client.websocket_connect("/api/v1/ws/slides?session=deck-ws") as ws, \
         api_client.websocket_connect("/api/v1/ws/slides?session=deck-other") as other:
        first = ws.receive_json()
        assert first["type"] == "state" and first["has_file"] is False
        assert other.receive_json()["type"] == "state"

        api_client.post("/api/v1/slides/file?session=deck-ws", content=PDF, headers=HEAD)
        state = ws.receive_json()
        assert state["type"] == "state" and state["has_file"] and state["version"] == 1

        api_client.post("/api/v1/slides/event?session=deck-ws", json={"slide_number": 3})
        assert ws.receive_json() == {"type": "page", "page": 3}

        # phiên khác không nhận gì: tin kế tiếp của nó là state của chính nó khi upload
        api_client.post("/api/v1/slides/file?session=deck-other", content=PDF, headers=HEAD)
        assert other.receive_json()["type"] == "state"


def test_late_joiner_gets_current_page(api_client):
    api_client.post("/api/v1/slides/file?session=deck-late", content=PDF, headers=HEAD)
    api_client.post("/api/v1/slides/event?session=deck-late", json={"slide_number": 5})
    with api_client.websocket_connect("/api/v1/ws/slides?session=deck-late") as ws:
        snap = ws.receive_json()
        assert snap["has_file"] and snap["page"] == 5
