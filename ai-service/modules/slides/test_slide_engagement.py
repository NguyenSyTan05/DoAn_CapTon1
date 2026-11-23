"""
Tests for the slide-engagement diagram feature:
be/service/slide_store.py (InMemorySlideEventStore + compute_engagement)
and the POST/GET /api/v1/slides/* endpoints.
"""

from __future__ import annotations

from modules.slides.slide_store import (
    InMemorySlideEventStore,
    SlideEventRecord,
    compute_engagement,
)


class TestInMemorySlideEventStore:
    def test_add_and_list(self):
        store = InMemorySlideEventStore()
        store.add(SlideEventRecord(1, "2026-09-26T10:00:00Z"))

        results = store.list_all()
        assert len(results) == 1
        assert results[0].slide_number == 1

    def test_list_sorted_by_started_at(self):
        store = InMemorySlideEventStore()
        store.add(SlideEventRecord(2, "2026-09-26T10:05:00Z"))
        store.add(SlideEventRecord(1, "2026-09-26T10:00:00Z"))

        results = store.list_all()
        assert [r.slide_number for r in results] == [1, 2]

    def test_clear_removes_everything(self):
        store = InMemorySlideEventStore()
        store.add(SlideEventRecord(1, "2026-09-26T10:00:00Z"))
        store.clear()

        assert store.list_all() == []


class TestComputeEngagement:
    def test_questions_bucketed_by_active_slide(self):
        events = [
            SlideEventRecord(1, "2026-09-26T10:00:00Z"),
            SlideEventRecord(2, "2026-09-26T10:10:00Z"),
            SlideEventRecord(3, "2026-09-26T10:20:00Z"),
        ]
        # 2 questions while slide 1 showing, 1 while slide 2, 0 while slide 3
        question_timestamps = [
            "2026-09-26T10:02:00Z",
            "2026-09-26T10:08:00Z",
            "2026-09-26T10:15:00Z",
        ]

        result = compute_engagement(events, question_timestamps)

        assert result == [
            {"slide_number": 1, "question_count": 2},
            {"slide_number": 2, "question_count": 1},
        ]

    def test_question_before_first_slide_is_ignored(self):
        events = [SlideEventRecord(1, "2026-09-26T10:00:00Z")]
        question_timestamps = ["2026-09-26T09:00:00Z"]

        result = compute_engagement(events, question_timestamps)

        assert result == []

    def test_no_slide_events_yields_empty_result(self):
        result = compute_engagement([], ["2026-09-26T10:00:00Z"])
        assert result == []

    def test_no_questions_yields_empty_result(self):
        events = [SlideEventRecord(1, "2026-09-26T10:00:00Z")]
        result = compute_engagement(events, [])
        assert result == []


class TestSlideEventsAPI:
    def test_record_then_engagement_empty_without_questions(self, api_client):
        resp = api_client.post("/api/v1/slides/event", json={"slide_number": 1})
        assert resp.status_code == 200
        assert resp.json()["slide_number"] == 1
        assert "started_at" in resp.json()

        engagement = api_client.get("/api/v1/slides/engagement")
        assert engagement.status_code == 200
        assert engagement.json() == {"slides": []}

    def test_engagement_correlates_with_submitted_questions(self, api_client):
        api_client.post("/api/v1/slides/event", json={"slide_number": 1})

        api_client.post("/api/v1/questions", json={
            "id": "q1", "text": "What is deadlock?",
            "timestamp": "2099-01-01T00:00:00Z",
        })
        api_client.post("/api/v1/questions", json={
            "id": "q2", "text": "What is recursion?",
            "timestamp": "2099-01-01T00:00:01Z",
        })

        engagement = api_client.get("/api/v1/slides/engagement").json()
        assert engagement == {"slides": [{"slide_number": 1, "question_count": 2}]}
