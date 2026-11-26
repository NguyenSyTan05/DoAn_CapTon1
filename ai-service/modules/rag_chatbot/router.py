"""
router.py (modules/rag_chatbot)
================================
Endpoints cho Chatbot Hỏi đáp Học liệu (RAG) và chuyển tiếp câu hỏi khó lên Giảng viên:
- `POST /api/v1/chatbot/ask`      : Hỏi nội dung Slide PDF & phụ đề bài giảng (kèm trích dẫn)
- `POST /api/v1/chatbot/escalate` : Chuyển câu hỏi vượt phạm vi học liệu sang hàng đợi Q&A của GV
- `GET  /api/v1/chatbot/history`  : Lịch sử hỏi đáp của người dùng trong phiên học
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request

from core.auth import ANY_MEMBER, STUDENT_OR_LECTURER, RoomAccess, require_room_access
from core.batcher import idempotency_store, parse_budget_ms
from core.governor import governor
from core.guardrails import inspect_prompt_injection
from core.pii_masker import mask_pii
from modules.qa.question_store import QuestionRecord, QuestionStore
from modules.rag_chatbot.schema import (
    ChatbotAskRequest,
    ChatbotAskResponse,
    ChatbotEscalateRequest,
    ChatbotEscalateResponse,
    ChatbotHistoryResponse,
)
from modules.rag_chatbot.service import RAGChatbotService
from modules.summary.summarizer import load_session_transcript_items

router = APIRouter()


@router.post("/api/v1/chatbot/ask", response_model=ChatbotAskResponse)
async def ask_lecture_chatbot(
    payload: ChatbotAskRequest,
    request: Request,
    access: RoomAccess = Depends(require_room_access(ANY_MEMBER, allow_closed=True)),
) -> ChatbotAskResponse:
    budget_ms = parse_budget_ms(request)
    idem_key = request.headers.get("idempotency-key")
    cached = idempotency_store.get(f"rag:{access.session}:{access.user.sub}:{idem_key}" if idem_key else None)
    if cached is not None:
        return cached

    injection_reason = inspect_prompt_injection(payload.question)
    if injection_reason:
        governor.record_guardrail_block()
        raise HTTPException(
            status_code=400,
            detail={"code": "prompt_injection_blocked", "message": injection_reason},
        )

    if not governor.check_and_consume_tokens(access.session, max(50, len(payload.question) // 3)):
        raise HTTPException(
            status_code=503,
            detail={
                "code": "governor_blocked",
                "message": "Trợ lý AI tạm ngắt theo chính sách kiểm soát tài nguyên (Kill Switch / Hạn mức phiên).",
            },
        )

    clean_q, pii_count = mask_pii(payload.question.strip())
    governor.record_pii(pii_count)

    live_rooms = getattr(request.app.state, "live_rooms", None)
    transcripts = load_session_transcript_items(access.session, live_rooms=live_rooms)
    slide_decks = getattr(request.app.state, "slide_decks", None)
    slide_texts: dict[int, str] = (
        dict(slide_decks.get(access.session).slide_texts) if slide_decks is not None else {}
    )
    aggregator = getattr(request.app.state, "aggregator", None)
    emb_model = getattr(aggregator, "embedding_model", None)
    rag_service: RAGChatbotService = request.app.state.rag_service

    coro = asyncio.to_thread(
        rag_service.answer_question,
        session_id=access.session,
        user_sub=access.user.sub,
        question=clean_q,
        slide_texts=slide_texts,
        transcript_items=transcripts,
        embedding_model=emb_model,
    )
    if budget_ms is not None:
        try:
            resp = await asyncio.wait_for(coro, timeout=budget_ms / 1000.0)
        except asyncio.TimeoutError as exc:
            governor.record_504()
            raise HTTPException(
                status_code=504,
                detail={"code": "budget_exceeded", "message": "Tra cứu RAG vượt ngân sách thời gian."},
            ) from exc
    else:
        resp = await coro

    if idem_key:
        idempotency_store.set(f"rag:{access.session}:{access.user.sub}:{idem_key}", resp)
    return resp


@router.post("/api/v1/chatbot/escalate", response_model=ChatbotEscalateResponse)
async def escalate_question_to_lecturer(
    payload: ChatbotEscalateRequest,
    request: Request,
    access: RoomAccess = Depends(require_room_access(STUDENT_OR_LECTURER)),
) -> ChatbotEscalateResponse:
    injection_reason = inspect_prompt_injection(payload.question)
    if injection_reason:
        governor.record_guardrail_block()
        raise HTTPException(status_code=400, detail={"code": "prompt_injection_blocked", "message": injection_reason})

    clean_q, pii_count = mask_pii(payload.question.strip())
    governor.record_pii(pii_count)

    esc_id = str(uuid.uuid4())
    q_id = f"esc_{esc_id[:8]}"
    q_store: QuestionStore = request.app.state.question_stores.get(access.session)
    q_store.add(
        QuestionRecord(
            id=q_id,
            text=f"[Cần GV giải đáp] {clean_q}",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    )
    return ChatbotEscalateResponse(
        escalation_id=esc_id,
        forwarded_question_id=q_id,
        message="Đã chuyển câu hỏi ẩn danh lên bảng điều phối Q&A của giảng viên!",
    )


@router.get("/api/v1/chatbot/history", response_model=ChatbotHistoryResponse)
async def get_chatbot_history(
    request: Request,
    access: RoomAccess = Depends(require_room_access(ANY_MEMBER, allow_closed=True)),
) -> ChatbotHistoryResponse:
    rag_service: RAGChatbotService = request.app.state.rag_service
    return ChatbotHistoryResponse(items=rag_service.list_history(access.session, access.user.sub))
