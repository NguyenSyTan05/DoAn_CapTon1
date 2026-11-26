"""
router.py (modules/qa)
========================
Q&A: câu hỏi ẩn danh của sinh viên (tự động che PII + lọc Prompt Injection +
hỗ trợ Idempotency-Key), câu trả lời của giảng viên (tự động dịch song ngữ
Anh–Việt `answer_vi` / `answer_en`) và đẩy real-time qua WebSocket `/api/v1/ws/qa`.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect

from core.ai import ai_service
from core.auth import ANY_MEMBER, LECTURER_ONLY, STUDENT_OR_LECTURER, require_room_access, verify_ws_access
from core.batcher import idempotency_store
from core.governor import governor
from core.guardrails import inspect_prompt_injection
from core.pii_masker import mask_pii
from core.session_scope import normalize_session, session_param
from modules.qa.answer_store import AnswerRecord, AnswerStore
from modules.qa.qa_broadcast import QAConnectionManager
from modules.qa.question_store import QuestionRecord, QuestionStore
from modules.qa.schema import (
    AnswerListResponse,
    AnswerOutput,
    AnswerRequest,
    QuestionInput,
    QuestionListResponse,
)
from modules.question_clustering.semantic_question_aggregator import (
    CustomSemanticQuestionAggregator,
    InvalidQuestionError,
)

router = APIRouter()


def _translate_bilingual_answer(raw_answer: str) -> tuple[str, str]:
    text = raw_answer.strip()
    if not text:
        return "", ""
    try:
        src = ai_service.detect_language(text)
        if src == "vi":
            vi_txt = text
            en_txt = (ai_service.transcript_text(text, "vi", "en") or "").strip()
        else:
            en_txt = text
            vi_txt = (ai_service.transcript_text(text, "en", "vi") or "").strip()
        return vi_txt or text, en_txt or text
    except Exception:
        return text, ""


@router.post(
    "/api/v1/questions",
    response_model=QuestionInput,
    dependencies=[Depends(require_room_access(STUDENT_OR_LECTURER))],
)
async def submit_question(
    payload: QuestionInput, request: Request, session: str = Depends(session_param)
):
    idem_key = request.headers.get("idempotency-key")
    cached = idempotency_store.get(f"qa:{session}:{idem_key}" if idem_key else None)
    if cached is not None:
        return cached

    injection_reason = inspect_prompt_injection(payload.text)
    if injection_reason:
        governor.record_guardrail_block()
        raise HTTPException(
            status_code=400,
            detail={"code": "prompt_injection_blocked", "message": injection_reason},
        )

    sanitized_text, pii_hits = mask_pii(payload.text)
    governor.record_pii(pii_hits)
    sanitized_payload = QuestionInput(
        id=payload.id,
        text=sanitized_text,
        timestamp=payload.timestamp,
    )

    try:
        CustomSemanticQuestionAggregator.parse_and_validate([sanitized_payload.model_dump()])
    except InvalidQuestionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    store: QuestionStore = request.app.state.question_stores.get(session)
    store.add(
        QuestionRecord(
            id=sanitized_payload.id,
            text=sanitized_payload.text,
            timestamp=sanitized_payload.timestamp,
        )
    )
    if idem_key:
        idempotency_store.set(f"qa:{session}:{idem_key}", sanitized_payload)
    return sanitized_payload


@router.get(
    "/api/v1/questions",
    response_model=QuestionListResponse,
    dependencies=[Depends(require_room_access(ANY_MEMBER))],
)
async def list_questions(request: Request, session: str = Depends(session_param)):
    store: QuestionStore = request.app.state.question_stores.get(session)
    return QuestionListResponse(
        questions=[QuestionInput(**r.__dict__) for r in store.list_all()]
    )


@router.delete(
    "/api/v1/questions/{question_id}",
    dependencies=[Depends(require_room_access(LECTURER_ONLY))],
)
async def remove_question(
    question_id: str, request: Request, session: str = Depends(session_param)
):
    store: QuestionStore = request.app.state.question_stores.get(session)
    removed = store.remove(question_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Question not found")
    return {"status": "deleted"}


@router.post(
    "/api/v1/answers",
    response_model=AnswerOutput,
    dependencies=[Depends(require_room_access(LECTURER_ONLY))],
)
async def submit_answer(
    payload: AnswerRequest, request: Request, session: str = Depends(session_param)
):
    ans_vi, ans_en = await asyncio.to_thread(_translate_bilingual_answer, payload.answer_text)
    store: AnswerStore = request.app.state.answer_stores.get(session)
    record = AnswerRecord(
        representative_id=payload.representative_id,
        representative_text=payload.representative_text,
        total_count=payload.total_count,
        answer_text=payload.answer_text,
        answered_at=datetime.now(timezone.utc).isoformat(),
        answer_vi=ans_vi,
        answer_en=ans_en,
    )
    store.upsert(record)
    output = AnswerOutput(**record.__dict__)

    qa_manager: QAConnectionManager = request.app.state.qa_manager
    await qa_manager.broadcast({"type": "upsert", "answer": output.model_dump()}, session)

    return output


@router.delete(
    "/api/v1/answers/{representative_id}",
    dependencies=[Depends(require_room_access(LECTURER_ONLY))],
)
async def remove_answer(
    representative_id: str, request: Request, session: str = Depends(session_param)
):
    store: AnswerStore = request.app.state.answer_stores.get(session)
    removed = store.delete(representative_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Answer not found")

    qa_manager: QAConnectionManager = request.app.state.qa_manager
    await qa_manager.broadcast({"type": "remove", "representative_id": representative_id}, session)

    return {"status": "deleted"}


@router.get(
    "/api/v1/answers",
    response_model=AnswerListResponse,
    dependencies=[Depends(require_room_access(ANY_MEMBER))],
)
async def list_answers(request: Request, session: str = Depends(session_param)):
    store: AnswerStore = request.app.state.answer_stores.get(session)
    return AnswerListResponse(answers=[AnswerOutput(**r.__dict__) for r in store.list_all()])


@router.websocket("/api/v1/ws/qa")
async def qa_websocket(websocket: WebSocket, session: str | None = Query(None)) -> None:
    scope = normalize_session(session)
    if scope is None:
        await websocket.close(code=1008)
        return
    if await verify_ws_access(websocket, scope, ANY_MEMBER) is None:
        await websocket.close(code=1008)
        return

    manager: QAConnectionManager = websocket.app.state.qa_manager
    store: AnswerStore = websocket.app.state.answer_stores.get(scope)

    await manager.connect(websocket, scope)
    try:
        snapshot = [AnswerOutput(**r.__dict__).model_dump() for r in store.list_all()]
        await websocket.send_json({"type": "snapshot", "answers": snapshot})

        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
