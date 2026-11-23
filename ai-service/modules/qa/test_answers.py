"""
Tests for the Lecturer Answers (Q&A) feature.

Tier 1: InMemoryAnswerStore directly (no HTTP, fast).
Tier 2: the 3 REST endpoints via api_client (tests/conftest.py) — same
stubbed-model TestClient pattern used in test_semantic_aggregation.py.
Tier 3: the /api/v1/ws/qa broadcast — snapshot on connect, upsert/remove
events pushed when a REST call changes the answer store.
"""

from __future__ import annotations

from modules.qa.answer_store import AnswerRecord, InMemoryAnswerStore


class TestInMemoryAnswerStore:
    def test_upsert_and_list(self):
        store = InMemoryAnswerStore()
        store.upsert(AnswerRecord("r1", "What is deadlock?", 3, "A deadlock is...", "2026-09-22T10:00:00Z"))

        results = store.list_all()
        assert len(results) == 1
        assert results[0].representative_id == "r1"

    def test_upsert_same_id_overwrites_not_duplicates(self):
        store = InMemoryAnswerStore()
        store.upsert(AnswerRecord("r1", "Q1", 3, "old answer", "2026-09-22T10:00:00Z"))
        store.upsert(AnswerRecord("r1", "Q1", 3, "new answer", "2026-09-22T10:05:00Z"))

        results = store.list_all()
        assert len(results) == 1
        assert results[0].answer_text == "new answer"

    def test_list_sorted_by_total_count_descending(self):
        store = InMemoryAnswerStore()
        store.upsert(AnswerRecord("small", "Q-small", 1, "a", "2026-09-22T10:00:00Z"))
        store.upsert(AnswerRecord("big", "Q-big", 10, "b", "2026-09-22T10:01:00Z"))

        results = store.list_all()
        assert [r.representative_id for r in results] == ["big", "small"]

    def test_delete_existing_returns_true_and_removes(self):
        store = InMemoryAnswerStore()
        store.upsert(AnswerRecord("r1", "Q1", 1, "a", "2026-09-22T10:00:00Z"))

        assert store.delete("r1") is True
        assert store.list_all() == []

    def test_delete_missing_returns_false(self):
        store = InMemoryAnswerStore()
        assert store.delete("does-not-exist") is False


class TestAnswersAPI:
    def test_submit_then_list(self, api_client):
        resp = api_client.post("/api/v1/answers", json={
            "representative_id": "r1",
            "representative_text": "What is deadlock?",
            "total_count": 3,
            "answer_text": "A deadlock happens when...",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["representative_id"] == "r1"
        assert "answered_at" in body

        listed = api_client.get("/api/v1/answers")
        assert listed.status_code == 200
        assert len(listed.json()["answers"]) == 1

    def test_resubmitting_same_id_overwrites(self, api_client):
        api_client.post("/api/v1/answers", json={
            "representative_id": "r1", "representative_text": "Q1",
            "total_count": 1, "answer_text": "first draft",
        })
        api_client.post("/api/v1/answers", json={
            "representative_id": "r1", "representative_text": "Q1",
            "total_count": 1, "answer_text": "final version",
        })

        listed = api_client.get("/api/v1/answers").json()["answers"]
        assert len(listed) == 1
        assert listed[0]["answer_text"] == "final version"

    def test_delete_answer(self, api_client):
        api_client.post("/api/v1/answers", json={
            "representative_id": "r1", "representative_text": "Q1",
            "total_count": 1, "answer_text": "A1",
        })

        resp = api_client.delete("/api/v1/answers/r1")
        assert resp.status_code == 200

        listed = api_client.get("/api/v1/answers")
        assert listed.json()["answers"] == []

    def test_delete_missing_returns_404(self, api_client):
        resp = api_client.delete("/api/v1/answers/does-not-exist")
        assert resp.status_code == 404

    def test_ranking_by_total_count_descending(self, api_client):
        api_client.post("/api/v1/answers", json={
            "representative_id": "small", "representative_text": "Q-small",
            "total_count": 1, "answer_text": "a",
        })
        api_client.post("/api/v1/answers", json={
            "representative_id": "big", "representative_text": "Q-big",
            "total_count": 10, "answer_text": "b",
        })

        listed = api_client.get("/api/v1/answers").json()["answers"]
        assert [a["representative_id"] for a in listed] == ["big", "small"]

    def test_empty_list_initially(self, api_client):
        resp = api_client.get("/api/v1/answers")
        assert resp.status_code == 200
        assert resp.json() == {"answers": []}


class TestAnswersWebSocketBroadcast:
    def test_snapshot_on_connect_is_empty_when_no_answers(self, api_client):
        with api_client.websocket_connect("/api/v1/ws/qa") as ws:
            msg = ws.receive_json()
            assert msg == {"type": "snapshot", "answers": []}

    def test_snapshot_reflects_existing_answers(self, api_client):
        api_client.post("/api/v1/answers", json={
            "representative_id": "r1", "representative_text": "Q1",
            "total_count": 2, "answer_text": "A1",
        })

        with api_client.websocket_connect("/api/v1/ws/qa") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "snapshot"
            assert len(msg["answers"]) == 1
            assert msg["answers"][0]["representative_id"] == "r1"

    def test_submit_broadcasts_upsert_to_connected_client(self, api_client):
        with api_client.websocket_connect("/api/v1/ws/qa") as ws:
            ws.receive_json()  # initial empty snapshot

            api_client.post("/api/v1/answers", json={
                "representative_id": "r1", "representative_text": "Q1",
                "total_count": 3, "answer_text": "A1",
            })

            msg = ws.receive_json()
            assert msg["type"] == "upsert"
            assert msg["answer"]["representative_id"] == "r1"
            assert msg["answer"]["answer_text"] == "A1"

    def test_delete_broadcasts_remove_to_connected_client(self, api_client):
        api_client.post("/api/v1/answers", json={
            "representative_id": "r1", "representative_text": "Q1",
            "total_count": 1, "answer_text": "A1",
        })

        with api_client.websocket_connect("/api/v1/ws/qa") as ws:
            ws.receive_json()  # snapshot already containing r1

            api_client.delete("/api/v1/answers/r1")

            msg = ws.receive_json()
            assert msg == {"type": "remove", "representative_id": "r1"}
