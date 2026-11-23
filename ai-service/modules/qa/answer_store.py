"""
answer_store.py
================
Persistence for lecturer answers to question clusters (Q&A feature).

[CUSTOM INTERFACE] `AnswerStore` is an abstract interface, same pattern
already used for `ClusteringStrategy` (clustering_strategies.py) and
`BilingualTranslator` (semantic_question_aggregator.py) in this codebase:
define a small interface, inject/swap the implementation.

`InMemoryAnswerStore` is the only implementation today — answers live only
for the lifetime of the server process, no database. When the team adds
PostgreSQL, write a `PostgresAnswerStore(AnswerStore)` implementing the same
3 methods and swap the one line in main.py's `lifespan()` that constructs
the store. No endpoint or frontend code needs to change for that swap.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class AnswerRecord:
    representative_id: str
    representative_text: str
    total_count: int
    answer_text: str
    answered_at: str  # ISO-8601 string, set by the caller (main.py)


class AnswerStore(ABC):
    @abstractmethod
    def list_all(self) -> list[AnswerRecord]:
        """Return every current answer. Implementations decide ordering."""
        raise NotImplementedError

    @abstractmethod
    def upsert(self, record: AnswerRecord) -> None:
        """Insert a new answer, or replace the existing one for the same
        representative_id (a lecturer editing/re-sending an answer)."""
        raise NotImplementedError

    @abstractmethod
    def delete(self, representative_id: str) -> bool:
        """Remove an answer. Returns True if something was removed."""
        raise NotImplementedError


class InMemoryAnswerStore(AnswerStore):
    def __init__(self) -> None:
        self._answers: dict[str, AnswerRecord] = {}

    def list_all(self) -> list[AnswerRecord]:
        # [DESIGN DECISION] Ranked by total_count descending (the topic the
        # most students asked about surfaces first — "push up" behaviour
        # requested for the student view), tie-broken by earliest answered
        # first. Mirrors the ordering convention already used by
        # rank_clusters() in semantic_question_aggregator.py.
        return sorted(self._answers.values(), key=lambda r: (-r.total_count, r.answered_at))

    def upsert(self, record: AnswerRecord) -> None:
        self._answers[record.representative_id] = record

    def delete(self, representative_id: str) -> bool:
        return self._answers.pop(representative_id, None) is not None
