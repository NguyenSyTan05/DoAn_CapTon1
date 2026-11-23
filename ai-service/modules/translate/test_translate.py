"""
Tests for the on-demand translation endpoint (POST /api/v1/translate) —
the "Translate" button next to a cluster's representative question on the
Teacher Dashboard. Uses the real NLLB model via AiService (already loaded
once per test session by the api_client fixture — see tests/conftest.py),
so these are genuine end-to-end checks, not mocked.
"""

from __future__ import annotations


class TestTranslateAPI:
    def test_empty_text_returns_422(self, api_client):
        resp = api_client.post("/api/v1/translate", json={"text": "   "})
        assert resp.status_code == 422

    def test_translate_vietnamese_to_english(self, api_client):
        resp = api_client.post(
            "/api/v1/translate", json={"text": "Deadlock là gì ạ?"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["source_lang"] == "vi"
        assert body["target_lang"] == "en"
        assert body["translated_text"].strip() != ""

    def test_translate_english_to_vietnamese(self, api_client):
        resp = api_client.post(
            "/api/v1/translate", json={"text": "What is a deadlock?"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["source_lang"] == "en"
        assert body["target_lang"] == "vi"
        assert body["translated_text"].strip() != ""
