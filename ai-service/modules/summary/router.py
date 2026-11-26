"""
router.py (modules/summary)
=============================
API REST cho tính năng Tóm tắt bài giảng (AI Lesson Summary), Bản đồ nhiệt
tương tác theo slide (Comprehension Heatmap), và Ghi chú học tập cá nhân.

Tất cả endpoint theo phòng đều truyền `allow_closed=True` để giảng viên và
sinh viên của lớp vẫn xem / tạo / xuất bản tóm tắt sau khi phiên học đã `ENDED`.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from core.auth import (
    ANY_MEMBER,
    LECTURER_ONLY,
    STUDENT_OR_LECTURER,
    RoomAccess,
    require_room_access,
)
from modules.qa.answer_store import AnswerStore
from modules.qa.question_store import QuestionStore
from modules.slides.slide_store import SlideEventStore
from modules.summary.schema import (
    LessonSummaryRecord,
    StudentNoteListResponse,
    StudentNoteOutput,
    StudentNoteRequest,
    SummaryGenerateRequest,
    SummaryUpdateRequest,
)
from modules.summary.summarizer import (
    build_clarifications,
    build_heatmap,
    generate_lesson_summary,
    load_session_transcript_items,
)
from modules.summary.summary_store import DiskBackedSummaryStore

router = APIRouter()


def _collect_session_inputs(request: Request, session: str) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, str],
    list[Any],
    dict[int, str],
]:
    live_rooms = getattr(request.app.state, "live_rooms", None)
    transcripts = load_session_transcript_items(session, live_rooms=live_rooms)

    q_store: QuestionStore = request.app.state.question_stores.get(session)
    questions = [
        {"id": r.id, "text": r.text, "timestamp": r.timestamp}
        for r in q_store.list_all()
    ]

    a_store: AnswerStore = request.app.state.answer_stores.get(session)
    answers_by_rep = {r.representative_id: r.answer_text for r in a_store.list_all()}

    s_store: SlideEventStore = request.app.state.slide_stores.get(session)
    slide_events = s_store.list_all()

    slide_decks = getattr(request.app.state, "slide_decks", None)
    slide_texts: dict[int, str] = (
        dict(slide_decks.get(session).slide_texts) if slide_decks is not None else {}
    )

    return transcripts, questions, answers_by_rep, slide_events, slide_texts


async def _run_generate(
    session: str,
    transcripts: list[dict[str, Any]],
    questions: list[dict[str, Any]],
    answers_by_rep: dict[str, str],
    slide_events: list[Any],
    *,
    slide_texts: dict[int, str] | None = None,
    aggregator: Any = None,
    lesson_title: str | None = None,
    lecturer_notes: str | None = None,
) -> LessonSummaryRecord:
    if aggregator is not None:
        return await asyncio.to_thread(
            generate_lesson_summary,
            session,
            transcripts,
            questions,
            answers_by_rep,
            slide_events,
            slide_texts=slide_texts,
            aggregator=aggregator,
            lesson_title=lesson_title,
            lecturer_notes=lecturer_notes,
        )
    return generate_lesson_summary(
        session,
        transcripts,
        questions,
        answers_by_rep,
        slide_events,
        slide_texts=slide_texts,
        aggregator=None,
        lesson_title=lesson_title,
        lecturer_notes=lecturer_notes,
    )


@router.get("/api/v1/summaries", response_model=LessonSummaryRecord)
async def get_lesson_summary(
    request: Request,
    auto: bool = Query(True, description="Tự động tổng hợp nếu chưa có bản lưu nhưng đã có phụ đề/câu hỏi"),
    access: RoomAccess = Depends(require_room_access(ANY_MEMBER, allow_closed=True)),
) -> LessonSummaryRecord:
    """Lấy bản tóm tắt bài giảng & Heatmap mới nhất của phiên học."""
    session = access.session
    store: DiskBackedSummaryStore = request.app.state.summary_stores.get(session)
    saved = store.get_summary()

    transcripts, questions, answers_by_rep, slide_events, slide_texts = _collect_session_inputs(request, session)
    aggregator = getattr(request.app.state, "aggregator", None)

    if saved is not None:
        q_timestamps = [q["timestamp"] for q in questions if q.get("timestamp")]
        fresh_heatmap = build_heatmap(slide_events, q_timestamps) or saved.heatmap
        if questions:
            fresh_clar = (
                await asyncio.to_thread(build_clarifications, questions, answers_by_rep, aggregator)
                if aggregator is not None
                else build_clarifications(questions, answers_by_rep, None)
            )
        else:
            fresh_clar = saved.further_clarification
        return saved.model_copy(
            update={
                "heatmap": fresh_heatmap,
                "further_clarification": fresh_clar,
                "transcript_count": max(saved.transcript_count, len(transcripts)),
                "question_count": max(saved.question_count, len(questions)),
            }
        )

    generated = await _run_generate(
        session,
        transcripts,
        questions,
        answers_by_rep,
        slide_events,
        slide_texts=slide_texts,
        aggregator=aggregator,
    )
    if auto and generated.generation_status == "COMPLETED":
        return store.save_summary(generated)
    return generated


@router.post("/api/v1/summaries/generate", response_model=LessonSummaryRecord)
async def regenerate_lesson_summary(
    payload: SummaryGenerateRequest,
    request: Request,
    access: RoomAccess = Depends(require_room_access(LECTURER_ONLY, allow_closed=True)),
) -> LessonSummaryRecord:
    """Giảng viên chủ động tạo hoặc tạo lại bản tóm tắt AI cho phiên học."""
    session = access.session
    store: DiskBackedSummaryStore = request.app.state.summary_stores.get(session)
    transcripts, questions, answers_by_rep, slide_events, slide_texts = _collect_session_inputs(request, session)
    aggregator = getattr(request.app.state, "aggregator", None)

    generated = await _run_generate(
        session,
        transcripts,
        questions,
        answers_by_rep,
        slide_events,
        slide_texts=slide_texts,
        aggregator=aggregator,
        lesson_title=payload.lesson_title,
        lecturer_notes=payload.lecturer_notes,
    )
    return store.save_summary(generated)


@router.put("/api/v1/summaries", response_model=LessonSummaryRecord)
async def update_lesson_summary(
    payload: SummaryUpdateRequest,
    request: Request,
    access: RoomAccess = Depends(require_room_access(LECTURER_ONLY, allow_closed=True)),
) -> LessonSummaryRecord:
    """Giảng viên hiệu đính nội dung bản tóm tắt và lưu phiên bản mới."""
    session = access.session
    store: DiskBackedSummaryStore = request.app.state.summary_stores.get(session)
    current = store.get_summary()
    if current is None:
        transcripts, questions, answers_by_rep, slide_events, slide_texts = _collect_session_inputs(request, session)
        current = await _run_generate(
            session,
            transcripts,
            questions,
            answers_by_rep,
            slide_events,
            slide_texts=slide_texts,
            aggregator=getattr(request.app.state, "aggregator", None),
        )

    patch: dict[str, Any] = {"generation_status": "COMPLETED"}
    if payload.lesson_title is not None and payload.lesson_title.strip():
        patch["lesson_title"] = payload.lesson_title.strip()
    if payload.detected_subject is not None and payload.detected_subject.strip():
        patch["detected_subject"] = payload.detected_subject.strip()
    if payload.overview is not None:
        patch["overview"] = payload.overview.strip()
    if payload.overview_en is not None:
        patch["overview_en"] = payload.overview_en.strip()
    if payload.key_takeaways is not None:
        patch["key_takeaways"] = [line.strip() for line in payload.key_takeaways if line.strip()]
    if payload.vocabulary is not None:
        patch["vocabulary"] = payload.vocabulary

    updated = current.model_copy(update=patch)
    return store.save_summary(updated)


@router.get("/api/v1/summaries/notes", response_model=StudentNoteListResponse)
async def list_personal_notes(
    request: Request,
    access: RoomAccess = Depends(require_room_access(ANY_MEMBER, allow_closed=True)),
) -> StudentNoteListResponse:
    """Lấy danh sách ghi chú cá nhân của người dùng hiện tại trong phiên học."""
    store: DiskBackedSummaryStore = request.app.state.summary_stores.get(access.session)
    return StudentNoteListResponse(notes=store.list_notes(access.user.sub))


@router.post("/api/v1/summaries/notes", response_model=StudentNoteOutput)
async def save_personal_note(
    payload: StudentNoteRequest,
    request: Request,
    access: RoomAccess = Depends(require_room_access(STUDENT_OR_LECTURER, allow_closed=True)),
) -> StudentNoteOutput:
    """Sinh viên / giảng viên tạo hoặc cập nhật ghi chú học tập cá nhân cho phiên học."""
    store: DiskBackedSummaryStore = request.app.state.summary_stores.get(access.session)
    return store.upsert_note(access.user.sub, access.session, payload)


@router.delete("/api/v1/summaries/notes/{note_id}")
async def delete_personal_note(
    note_id: str,
    request: Request,
    access: RoomAccess = Depends(require_room_access(STUDENT_OR_LECTURER, allow_closed=True)),
) -> dict[str, str]:
    store: DiskBackedSummaryStore = request.app.state.summary_stores.get(access.session)
    if not store.delete_note(access.user.sub, note_id):
        raise HTTPException(status_code=404, detail="Note not found")
    return {"status": "deleted"}
