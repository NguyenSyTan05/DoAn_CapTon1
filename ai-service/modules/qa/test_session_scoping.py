"""
Tests cho việc tách dữ liệu theo phiên học (?session=<id>): câu hỏi, câu trả lời,
sự kiện slide và WebSocket Q&A của phiên này không lọt sang phiên khác. Không truyền
session = phạm vi mặc định (hành vi cũ).
"""

from __future__ import annotations

from datetime import datetime, timezone


def question(qid: str, text: str = "What is regression testing?") -> dict:
    return {"id": qid, "text": text, "timestamp": datetime.now(timezone.utc).isoformat()}


def answer(rid: str, text: str = "It re-runs old tests.") -> dict:
    return {"representative_id": rid, "representative_text": "q", "total_count": 2, "answer_text": text}


class TestQuestionsPerSession:
    def test_questions_isolated(self, api_client):
        assert api_client.post("/api/v1/questions?session=sess-A", json=question("qa1")).status_code == 200
        assert api_client.post("/api/v1/questions?session=sess-B", json=question("qb1")).status_code == 200

        a = [q["id"] for q in api_client.get("/api/v1/questions?session=sess-A").json()["questions"]]
        b = [q["id"] for q in api_client.get("/api/v1/questions?session=sess-B").json()["questions"]]
        default = [q["id"] for q in api_client.get("/api/v1/questions").json()["questions"]]
        assert a == ["qa1"] and b == ["qb1"]
        assert "qa1" not in default and "qb1" not in default

    def test_delete_only_affects_own_session(self, api_client):
        api_client.post("/api/v1/questions?session=sess-C", json=question("same-id"))
        api_client.post("/api/v1/questions?session=sess-D", json=question("same-id"))
        assert api_client.delete("/api/v1/questions/same-id?session=sess-C").status_code == 200
        assert api_client.get("/api/v1/questions?session=sess-C").json()["questions"] == []
        assert len(api_client.get("/api/v1/questions?session=sess-D").json()["questions"]) == 1

    def test_invalid_session_rejected(self, api_client):
        resp = api_client.post("/api/v1/questions?session=../x", json=question("bad"))
        assert resp.status_code == 422


class TestAnswersPerSession:
    def test_answers_isolated_and_broadcast_scoped(self, api_client):
        with api_client.websocket_connect("/api/v1/ws/qa?session=room-1") as ws1, \
             api_client.websocket_connect("/api/v1/ws/qa?session=room-2") as ws2:
            assert ws1.receive_json() == {"type": "snapshot", "answers": []}
            assert ws2.receive_json() == {"type": "snapshot", "answers": []}

            assert api_client.post("/api/v1/answers?session=room-1", json=answer("r1")).status_code == 200

            msg = ws1.receive_json()
            assert msg["type"] == "upsert" and msg["answer"]["representative_id"] == "r1"
            # room-2 không nhận gì: tin kế tiếp của nó phải là sự kiện của chính room-2
            assert api_client.post("/api/v1/answers?session=room-2", json=answer("r2")).status_code == 200
            msg2 = ws2.receive_json()
            assert msg2["answer"]["representative_id"] == "r2"

        ids1 = [a["representative_id"] for a in api_client.get("/api/v1/answers?session=room-1").json()["answers"]]
        ids2 = [a["representative_id"] for a in api_client.get("/api/v1/answers?session=room-2").json()["answers"]]
        assert ids1 == ["r1"] and ids2 == ["r2"]

    def test_snapshot_contains_only_own_session(self, api_client):
        api_client.post("/api/v1/answers?session=room-3", json=answer("only3"))
        with api_client.websocket_connect("/api/v1/ws/qa?session=room-3") as ws:
            snap = ws.receive_json()
            assert [a["representative_id"] for a in snap["answers"]] == ["only3"]
        with api_client.websocket_connect("/api/v1/ws/qa?session=room-4") as ws:
            assert ws.receive_json()["answers"] == []

    def test_legacy_default_scope_still_works(self, api_client):
        with api_client.websocket_connect("/api/v1/ws/qa") as ws:
            ws.receive_json()
            api_client.post("/api/v1/answers", json=answer("legacy"))
            assert ws.receive_json()["answer"]["representative_id"] == "legacy"
        api_client.delete("/api/v1/answers/legacy")


class TestSlidesPerSession:
    def test_engagement_uses_same_session_questions(self, api_client):
        api_client.post("/api/v1/slides/event?session=slide-1", json={"slide_number": 1})
        api_client.post("/api/v1/questions?session=slide-1", json=question("sq1"))
        api_client.post("/api/v1/questions?session=slide-2", json=question("sq2"))

        s1 = api_client.get("/api/v1/slides/engagement?session=slide-1").json()["slides"]
        s2 = api_client.get("/api/v1/slides/engagement?session=slide-2").json()["slides"]
        assert sum(s["question_count"] for s in s1) == 1
        assert s2 == [] or sum(s["question_count"] for s in s2) == 0
