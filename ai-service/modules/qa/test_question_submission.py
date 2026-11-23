"""
Tests for server-side question storage (be/service/question_store.py) and
the POST/GET /api/v1/questions endpoints — the fix for questions submitted
from one device never reaching another device's localStorage.

Tier 1: InMemoryQuestionStore directly (no HTTP, fast).
Tier 2: the 2 REST endpoints via api_client (tests/conftest.py).
"""

from __future__ import annotations

from modules.qa.question_store import InMemoryQuestionStore, QuestionRecord


class TestInMemoryQuestionStore:
    def test_add_and_list(self):
        store = InMemoryQuestionStore()
        store.add(QuestionRecord("q1", "What is deadlock?", "2026-09-22T10:00:00Z"))

        results = store.list_all()
        assert len(results) == 1
        assert results[0].id == "q1"

    def test_add_same_id_overwrites_not_duplicates(self):
        store = InMemoryQuestionStore()
        store.add(QuestionRecord("q1", "first wording", "2026-09-22T10:00:00Z"))
        store.add(QuestionRecord("q1", "retried wording", "2026-09-22T10:00:01Z"))

        results = store.list_all()
        assert len(results) == 1
        assert results[0].text == "retried wording"

    def test_list_sorted_by_timestamp(self):
        store = InMemoryQuestionStore()
        store.add(QuestionRecord("later", "b", "2026-09-22T10:05:00Z"))
        store.add(QuestionRecord("earlier", "a", "2026-09-22T10:00:00Z"))

        results = store.list_all()
        assert [r.id for r in results] == ["earlier", "later"]

    def test_remove_existing_returns_true(self):
        store = InMemoryQuestionStore()
        store.add(QuestionRecord("q1", "a", "2026-09-22T10:00:00Z"))

        assert store.remove("q1") is True
        assert store.list_all() == []

    def test_remove_missing_returns_false(self):
        store = InMemoryQuestionStore()
        assert store.remove("does-not-exist") is False

    def test_clear_removes_everything(self):
        store = InMemoryQuestionStore()
        store.add(QuestionRecord("q1", "a", "2026-09-22T10:00:00Z"))
        store.clear()

        assert store.list_all() == []


class TestQuestionSubmissionAPI:
    def test_submit_then_list(self, api_client):
        resp = api_client.post("/api/v1/questions", json={
            "id": "q1", "text": "What is deadlock?", "timestamp": "2026-09-22T10:00:00Z",
        })
        assert resp.status_code == 200
        assert resp.json()["id"] == "q1"

        listed = api_client.get("/api/v1/questions")
        assert listed.status_code == 200
        assert len(listed.json()["questions"]) == 1

    def test_two_different_devices_both_reach_the_same_store(self, api_client):
        """The whole point of this feature: two independent POSTs (as if
        from two different students' browsers) both end up visible via a
        single GET — no per-browser storage involved."""
        api_client.post("/api/v1/questions", json={
            "id": "student-a", "text": "Question from device A", "timestamp": "2026-09-22T10:00:00Z",
        })
        api_client.post("/api/v1/questions", json={
            "id": "student-b", "text": "Question from device B", "timestamp": "2026-09-22T10:00:05Z",
        })

        listed = api_client.get("/api/v1/questions").json()["questions"]
        assert {q["id"] for q in listed} == {"student-a", "student-b"}

    def test_empty_text_returns_422(self, api_client):
        resp = api_client.post("/api/v1/questions", json={
            "id": "q1", "text": "   ", "timestamp": "2026-09-22T10:00:00Z",
        })
        assert resp.status_code == 422

    def test_malformed_timestamp_returns_422(self, api_client):
        resp = api_client.post("/api/v1/questions", json={
            "id": "q1", "text": "hello", "timestamp": "not-a-date",
        })
        assert resp.status_code == 422

    def test_resubmitting_same_id_overwrites(self, api_client):
        api_client.post("/api/v1/questions", json={
            "id": "q1", "text": "first wording", "timestamp": "2026-09-22T10:00:00Z",
        })
        api_client.post("/api/v1/questions", json={
            "id": "q1", "text": "retried wording", "timestamp": "2026-09-22T10:00:01Z",
        })

        listed = api_client.get("/api/v1/questions").json()["questions"]
        assert len(listed) == 1
        assert listed[0]["text"] == "retried wording"

    def test_delete_question(self, api_client):
        api_client.post("/api/v1/questions", json={
            "id": "q1", "text": "What is deadlock?", "timestamp": "2026-09-22T10:00:00Z",
        })

        resp = api_client.delete("/api/v1/questions/q1")
        assert resp.status_code == 200

        listed = api_client.get("/api/v1/questions").json()["questions"]
        assert listed == []

    def test_delete_missing_returns_404(self, api_client):
        resp = api_client.delete("/api/v1/questions/does-not-exist")
        assert resp.status_code == 404

    def test_empty_list_initially(self, api_client):
        resp = api_client.get("/api/v1/questions")
        assert resp.status_code == 200
        assert resp.json() == {"questions": []}
