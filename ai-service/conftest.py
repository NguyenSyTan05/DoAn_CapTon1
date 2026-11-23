"""
conftest.py
============
Shared pytest fixtures for be/tests/. Extracted from
test_semantic_aggregation.py so test_answers.py (and any future API test
module) can reuse the same stubbed-model TestClient without duplicating it.
"""

from __future__ import annotations

import sys
import types

import numpy as np
import pytest


class _StubSentenceTransformer:
    """[TEST DOUBLE] Stands in for the real multilingual model so API
    wiring can be tested without model-hub access. Returns deterministic
    pseudo-random unit-ish vectors seeded by text hash — NOT semantically
    meaningful, only shape/type-correct."""

    def __init__(self, model_name: str, device: str = "cpu"):
        self._dim = 384

    def get_sentence_embedding_dimension(self) -> int:
        return self._dim

    def encode(self, texts, batch_size=32, convert_to_numpy=True, show_progress_bar=False,
               normalize_embeddings=False):
        rng = np.random.default_rng(abs(hash(tuple(texts))) % (2**32))
        return rng.normal(size=(len(texts), self._dim)).astype(np.float32)


@pytest.fixture()
def stub_model_module(monkeypatch):
    fake_module = types.ModuleType("sentence_transformers")
    fake_module.SentenceTransformer = _StubSentenceTransformer
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
    yield


@pytest.fixture()
def api_client(stub_model_module):
    from fastapi.testclient import TestClient
    import main
    with TestClient(main.app) as client:
        yield client
