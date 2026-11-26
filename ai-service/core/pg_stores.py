"""
pg_stores.py (core)
====================
Lớp đồng bộ lưu trữ hai chiều (Write-Through / Hybrid) giữa `ai-service` và
cơ sở dữ liệu PostgreSQL (`db.sql`) cho:
1. `PostgresQuestionStore`  -> bảng `questions`
2. `PostgresAnswerStore`    -> bảng `question_groups` + `answers`
3. `PostgresSlideEventStore`-> bảng `lecture_slides` / cache sự kiện
4. `PostgresSummarySync`    -> bảng `lesson_summaries`, `lesson_summary_versions`, `domain_keywords`

Chế độ hoạt động điều khiển qua biến môi trường:
- `AI_STORAGE_BACKEND=memory` (mặc định an toàn khi dev độc lập / chưa nối DB)
- `AI_STORAGE_BACKEND=postgres` (đồng bộ sang PostgreSQL thông qua `DATABASE_URL`
  mà vẫn giữ đệm RAM tốc độ cao để không làm chậm luồng WebSocket thời gian thực).
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from modules.qa.answer_store import AnswerRecord, AnswerStore, InMemoryAnswerStore
from modules.qa.question_store import InMemoryQuestionStore, QuestionRecord, QuestionStore
from modules.slides.slide_store import InMemorySlideEventStore, SlideEventRecord, SlideEventStore
from modules.summary.schema import LessonSummaryRecord
from modules.summary.summary_store import DiskBackedSummaryStore

logger = logging.getLogger("classbridge.pg_stores")

_engine: Engine | None = None


def _is_valid_uuid(value: str) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, TypeError):
        return False


def _deterministic_uuid(namespace_key: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_OID, namespace_key))


def get_pg_engine() -> Engine | None:
    """Khởi tạo kết nối SQLAlchemy tới PostgreSQL khi `AI_STORAGE_BACKEND=postgres`."""
    global _engine
    mode = os.getenv("AI_STORAGE_BACKEND", "memory").strip().lower()
    if mode not in ("postgres", "hybrid"):
        return None
    if _engine is not None:
        return _engine
    db_url = os.getenv("DATABASE_URL", "").strip()
    if not db_url.startswith(("postgresql://", "postgresql+psycopg2://")):
        logger.warning(
            "AI_STORAGE_BACKEND=%s nhưng thiếu DATABASE_URL hợp lệ; giữ chế độ InMemory.",
            mode,
        )
        return None
    try:
        _engine = create_engine(db_url, pool_pre_ping=True, pool_size=5, max_overflow=5)
        logger.info("Đã kết nối kho lưu trữ PostgreSQL cho ai-service.")
        return _engine
    except Exception:
        logger.warning("Không khởi tạo được kết nối PostgreSQL, tự lùi về InMemory", exc_info=True)
        return None


class PostgresQuestionStore(QuestionStore):
    """Lưu trữ câu hỏi trên RAM tốc độ cao đồng thời đồng bộ sang bảng `questions`."""

    def __init__(self, session: str = "") -> None:
        self._session = session
        self._mem = InMemoryQuestionStore()
        self._hydrated = False

    def _hydrate_once(self) -> None:
        if self._hydrated:
            return
        self._hydrated = True
        eng = get_pg_engine()
        if eng is None or not _is_valid_uuid(self._session):
            return
        try:
            with eng.connect() as conn:
                rows = conn.execute(
                    text(
                        """
                        SELECT question_id::text AS id, original_text AS text, created_at
                        FROM questions
                        WHERE session_id = CAST(:sid AS uuid)
                        ORDER BY created_at ASC
                        """
                    ),
                    {"sid": self._session},
                ).mappings().all()
                for r in rows:
                    ts = r["created_at"].isoformat() if hasattr(r["created_at"], "isoformat") else str(r["created_at"])
                    self._mem.add(QuestionRecord(id=r["id"], text=r["text"], timestamp=ts))
        except Exception:
            logger.debug("Không nạp được lịch sử câu hỏi từ PostgreSQL cho phiên %s", self._session, exc_info=True)

    def add(self, record: QuestionRecord) -> None:
        self._hydrate_once()
        self._mem.add(record)
        eng = get_pg_engine()
        if eng is None or not _is_valid_uuid(self._session):
            return
        q_uuid = record.id if _is_valid_uuid(record.id) else _deterministic_uuid(f"q:{self._session}:{record.id}")
        try:
            with eng.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO questions (question_id, session_id, original_text, status)
                        VALUES (CAST(:qid AS uuid), CAST(:sid AS uuid), :txt, 'OPEN')
                        ON CONFLICT (question_id) DO UPDATE SET original_text = EXCLUDED.original_text
                        """
                    ),
                    {"qid": q_uuid, "sid": self._session, "txt": record.text},
                )
        except Exception:
            logger.debug("Ghi câu hỏi sang PostgreSQL thất bại (vẫn giữ an toàn trên RAM)", exc_info=True)

    def list_all(self) -> list[QuestionRecord]:
        self._hydrate_once()
        return self._mem.list_all()

    def remove(self, question_id: str) -> bool:
        self._hydrate_once()
        removed = self._mem.remove(question_id)
        eng = get_pg_engine()
        if eng is not None and _is_valid_uuid(self._session):
            q_uuid = question_id if _is_valid_uuid(question_id) else _deterministic_uuid(f"q:{self._session}:{question_id}")
            try:
                with eng.begin() as conn:
                    conn.execute(
                        text("DELETE FROM questions WHERE question_id = CAST(:qid AS uuid)"),
                        {"qid": q_uuid},
                    )
            except Exception:
                logger.debug("Xóa câu hỏi trên PostgreSQL thất bại", exc_info=True)
        return removed


class PostgresAnswerStore(AnswerStore):
    """Lưu trữ câu trả lời của giảng viên trên RAM kèm đồng bộ sang `question_groups` & `answers`."""

    def __init__(self, session: str = "") -> None:
        self._session = session
        self._mem = InMemoryAnswerStore()
        self._hydrated = False

    def _hydrate_once(self) -> None:
        if self._hydrated:
            return
        self._hydrated = True
        eng = get_pg_engine()
        if eng is None or not _is_valid_uuid(self._session):
            return
        try:
            with eng.connect() as conn:
                rows = conn.execute(
                    text(
                        """
                        SELECT
                            COALESCE(qg.group_id::text, a.answer_id::text) AS rep_id,
                            COALESCE(qg.canonical_question, qg.topic_label, '') AS rep_text,
                            COALESCE(qg.question_count, 1) AS total_count,
                            a.answer_en,
                            a.answer_vi,
                            a.created_at
                        FROM answers a
                        LEFT JOIN question_groups qg ON qg.group_id = a.group_id
                        WHERE qg.session_id = CAST(:sid AS uuid)
                        ORDER BY a.created_at ASC
                        """
                    ),
                    {"sid": self._session},
                ).mappings().all()
                for r in rows:
                    ts = r["created_at"].isoformat() if hasattr(r["created_at"], "isoformat") else str(r["created_at"])
                    self._mem.upsert(
                        AnswerRecord(
                            representative_id=r["rep_id"],
                            representative_text=r["rep_text"],
                            total_count=int(r["total_count"] or 1),
                            answer_text=str(r["answer_vi"] or r["answer_en"] or ""),
                            answered_at=ts,
                            answer_vi=str(r["answer_vi"] or ""),
                            answer_en=str(r["answer_en"] or ""),
                        )
                    )
        except Exception:
            logger.debug("Không nạp được lịch sử câu trả lời từ PostgreSQL", exc_info=True)

    def list_all(self) -> list[AnswerRecord]:
        self._hydrate_once()
        return self._mem.list_all()

    def upsert(self, record: AnswerRecord) -> None:
        self._hydrate_once()
        self._mem.upsert(record)
        eng = get_pg_engine()
        if eng is None or not _is_valid_uuid(self._session):
            return
        grp_uuid = (
            record.representative_id
            if _is_valid_uuid(record.representative_id)
            else _deterministic_uuid(f"grp:{self._session}:{record.representative_id}")
        )
        ans_uuid = _deterministic_uuid(f"ans:{self._session}:{record.representative_id}")
        try:
            with eng.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO question_groups (
                            group_id, session_id, topic_label, canonical_question, question_count, status
                        ) VALUES (
                            CAST(:gid AS uuid), CAST(:sid AS uuid), :topic, :canon, :cnt, 'ANSWERED'
                        )
                        ON CONFLICT (group_id) DO UPDATE SET
                            canonical_question = EXCLUDED.canonical_question,
                            question_count = EXCLUDED.question_count,
                            status = 'ANSWERED'
                        """
                    ),
                    {
                        "gid": grp_uuid,
                        "sid": self._session,
                        "topic": record.representative_text[:200],
                        "canon": record.representative_text,
                        "cnt": max(1, record.total_count),
                    },
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO answers (
                            answer_id, group_id, answer_vi, answer_en, answer_type
                        ) VALUES (
                            CAST(:aid AS uuid), CAST(:gid AS uuid), :ans_vi, :ans_en, 'MANUAL'
                        )
                        ON CONFLICT (answer_id) DO UPDATE SET
                            answer_vi = EXCLUDED.answer_vi,
                            answer_en = EXCLUDED.answer_en
                        """
                    ),
                    {
                        "aid": ans_uuid,
                        "gid": grp_uuid,
                        "ans_vi": record.answer_vi or record.answer_text,
                        "ans_en": record.answer_en or record.answer_text,
                    },
                )
        except Exception:
            logger.debug("Ghi câu trả lời sang PostgreSQL thất bại", exc_info=True)

    def delete(self, representative_id: str) -> bool:
        self._hydrate_once()
        removed = self._mem.delete(representative_id)
        eng = get_pg_engine()
        if eng is not None and _is_valid_uuid(self._session):
            ans_uuid = _deterministic_uuid(f"ans:{self._session}:{representative_id}")
            try:
                with eng.begin() as conn:
                    conn.execute(
                        text("DELETE FROM answers WHERE answer_id = CAST(:aid AS uuid)"),
                        {"aid": ans_uuid},
                    )
            except Exception:
                logger.debug("Xóa câu trả lời trên PostgreSQL thất bại", exc_info=True)
        return removed


class PostgresSlideEventStore(SlideEventStore):
    """Lưu sự kiện lật trang Slide trên RAM và cập nhật bảng `lecture_slides` khi nối PostgreSQL."""

    def __init__(self, session: str = "") -> None:
        self._session = session
        self._mem = InMemorySlideEventStore()

    def add(self, record: SlideEventRecord) -> None:
        self._mem.add(record)
        eng = get_pg_engine()
        if eng is None or not _is_valid_uuid(self._session):
            return
        try:
            with eng.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO lecture_slides (session_id, slide_number, title)
                        VALUES (CAST(:sid AS uuid), :snum, :title)
                        ON CONFLICT (session_id, slide_number) DO NOTHING
                        """
                    ),
                    {
                        "sid": self._session,
                        "snum": record.slide_number,
                        "title": f"Slide {record.slide_number}",
                    },
                )
        except Exception:
            logger.debug("Ghi sự kiện slide sang PostgreSQL thất bại", exc_info=True)

    def list_all(self) -> list[SlideEventRecord]:
        return self._mem.list_all()


class HybridSummaryStore(DiskBackedSummaryStore):
    """Mở rộng `DiskBackedSummaryStore`: vừa lưu JSON xuống đĩa vừa đồng bộ sang `lesson_summaries`."""

    def save_summary(self, record: LessonSummaryRecord) -> LessonSummaryRecord:
        saved = super().save_summary(record)
        eng = get_pg_engine()
        if eng is None or not _is_valid_uuid(self._session):
            return saved
        sum_uuid = _deterministic_uuid(f"summary:{self._session}")
        status_db = "COMPLETED" if saved.generation_status == "COMPLETED" else "PENDING"
        try:
            with eng.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO lesson_summaries (
                            summary_id, session_id, lesson_title, detected_subject, overview,
                            lecture_structure, key_concepts, vocabulary, examples,
                            key_takeaways, further_clarification, model_name, generation_status
                        ) VALUES (
                            CAST(:sum_id AS uuid), CAST(:sid AS uuid), :title, :subj, :overview,
                            CAST(:struct AS jsonb), CAST(:concepts AS jsonb), CAST(:vocab AS jsonb),
                            CAST(:examples AS jsonb), CAST(:takeaways AS jsonb), CAST(:clar AS jsonb),
                            :model_name, :status
                        )
                        ON CONFLICT (summary_id) DO UPDATE SET
                            lesson_title = EXCLUDED.lesson_title,
                            detected_subject = EXCLUDED.detected_subject,
                            overview = EXCLUDED.overview,
                            lecture_structure = EXCLUDED.lecture_structure,
                            key_concepts = EXCLUDED.key_concepts,
                            vocabulary = EXCLUDED.vocabulary,
                            examples = EXCLUDED.examples,
                            key_takeaways = EXCLUDED.key_takeaways,
                            further_clarification = EXCLUDED.further_clarification,
                            model_name = EXCLUDED.model_name,
                            generation_status = EXCLUDED.generation_status
                        """
                    ),
                    {
                        "sum_id": sum_uuid,
                        "sid": self._session,
                        "title": saved.lesson_title,
                        "subj": saved.detected_subject,
                        "overview": saved.overview,
                        "struct": json.dumps([s.model_dump() for s in saved.lecture_structure], ensure_ascii=False),
                        "concepts": json.dumps([c.model_dump() for c in saved.key_concepts], ensure_ascii=False),
                        "vocab": json.dumps([v.model_dump() for v in saved.vocabulary], ensure_ascii=False),
                        "examples": json.dumps([e.model_dump() for e in saved.examples], ensure_ascii=False),
                        "takeaways": json.dumps(saved.key_takeaways, ensure_ascii=False),
                        "clar": json.dumps([c.model_dump() for c in saved.further_clarification], ensure_ascii=False),
                        "model_name": saved.model_name,
                        "status": status_db,
                    },
                )
        except Exception:
            logger.debug("Đồng bộ lesson_summaries sang PostgreSQL thất bại", exc_info=True)
        return saved


def build_question_store(session: str) -> QuestionStore:
    if os.getenv("AI_STORAGE_BACKEND", "memory").strip().lower() in ("postgres", "hybrid"):
        return PostgresQuestionStore(session=session)
    return InMemoryQuestionStore()


def build_answer_store(session: str) -> AnswerStore:
    if os.getenv("AI_STORAGE_BACKEND", "memory").strip().lower() in ("postgres", "hybrid"):
        return PostgresAnswerStore(session=session)
    return InMemoryAnswerStore()


def build_slide_store(session: str) -> SlideEventStore:
    if os.getenv("AI_STORAGE_BACKEND", "memory").strip().lower() in ("postgres", "hybrid"):
        return PostgresSlideEventStore(session=session)
    return InMemorySlideEventStore()


def build_summary_store(session: str) -> DiskBackedSummaryStore:
    if os.getenv("AI_STORAGE_BACKEND", "memory").strip().lower() in ("postgres", "hybrid"):
        return HybridSummaryStore(session=session)
    return DiskBackedSummaryStore(session=session)
