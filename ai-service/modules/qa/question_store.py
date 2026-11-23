"""
question_store.py
===================
[CUSTOM INTERFACE] Server-side storage for student-submitted questions —
same swappable pattern as answer_store.py (see that file's docstring).

Without this, a question submitted from a student's own device only ever
lives in that device's localStorage and never reaches the lecturer's
Dashboard on a different device — this was the biggest remaining gap noted
in architecture.md's "Known Gaps" (localStorage is per-browser, multi-device
classrooms don't share question data).

InMemoryQuestionStore is the only implementation today — questions live
only for the lifetime of the server process, no database. When the team
adds PostgreSQL, write a PostgresQuestionStore(QuestionStore) implementing
the same methods and swap the one line in main.py's lifespan(). No endpoint
or frontend code needs to change for that swap.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class QuestionRecord:
    id: str
    text: str
    timestamp: str


class QuestionStore(ABC):
    @abstractmethod
    def list_all(self) -> list[QuestionRecord]:
        """Return every stored question, oldest first."""
        raise NotImplementedError

    @abstractmethod
    def add(self, record: QuestionRecord) -> None:
        """Add a question. Same id overwrites (idempotent — a client retry
        after a network hiccup must not create a duplicate)."""
        raise NotImplementedError

    @abstractmethod
    def remove(self, question_id: str) -> bool:
        """Remove one question by id. Returns True if something was
        removed — used by the Dashboard's "Remove topic" action so a
        deleted cluster's questions don't reappear on the next fetch."""
        raise NotImplementedError

    @abstractmethod
    def clear(self) -> None:
        """Remove every stored question — e.g. starting a fresh session
        without restarting the server."""
        raise NotImplementedError


class InMemoryQuestionStore(QuestionStore):
    def __init__(self) -> None:
        self._questions: dict[str, QuestionRecord] = {}

    def list_all(self) -> list[QuestionRecord]:
        return sorted(self._questions.values(), key=lambda r: r.timestamp)

    def add(self, record: QuestionRecord) -> None:
        self._questions[record.id] = record

    def remove(self, question_id: str) -> bool:
        return self._questions.pop(question_id, None) is not None

    def clear(self) -> None:
        self._questions.clear()
