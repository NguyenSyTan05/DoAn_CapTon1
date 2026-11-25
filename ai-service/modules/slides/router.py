"""
router.py (modules/slides)
============================
Slide Engagement Diagram. Giảng viên tự upload PDF (SlideViewer.tsx) và
điều hướng slide trong app — mỗi lần chuyển slide là một sự kiện CHẮC CHẮN
(đổi số trang), không cần computer vision/AI để "đoán" đổi slide qua
screen share.

Phụ thuộc chéo cụm (có chủ đích): slide_engagement đọc QuestionStore của
cụm qa (qua app.state) để đối chiếu timestamp câu hỏi với timestamp slide.
"""

from __future__ import annotations

from datetime import datetime, timezone

from urllib.parse import quote, unquote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect

from core.auth import ANY_MEMBER, LECTURER_ONLY, require_room_access
from core.session_scope import normalize_session, session_param
from modules.qa.qa_broadcast import QAConnectionManager
from modules.slides.deck_store import MAX_PDF_BYTES, SlideDeck

from modules.qa.question_store import QuestionStore
from modules.slides.schema import (
    SlideEngagementResponse,
    SlideEventOutput,
    SlideEventRequest,
)
from modules.slides.slide_store import (
    SlideEventRecord,
    SlideEventStore,
    compute_engagement,
)

router = APIRouter()


@router.post(
    "/api/v1/slides/event",
    response_model=SlideEventOutput,
    dependencies=[Depends(require_room_access(LECTURER_ONLY))],
)
async def record_slide_event(
    payload: SlideEventRequest, request: Request, session: str = Depends(session_param)
):
    """Giảng viên gọi mỗi khi chuyển slide trong SlideViewer."""
    store: SlideEventStore = request.app.state.slide_stores.get(session)
    record = SlideEventRecord(
        slide_number=payload.slide_number,
        started_at=datetime.now(timezone.utc).isoformat(),
    )
    store.add(record)

    # [CHIA SẺ SLIDE] sinh viên theo số trang giảng viên đang mở
    deck: SlideDeck = request.app.state.slide_decks.get(session)
    deck.set_page(payload.slide_number)
    manager: QAConnectionManager = request.app.state.slide_manager
    await manager.broadcast({"type": "page", "page": deck.page}, session)
    return SlideEventOutput(**record.__dict__)


@router.get(
    "/api/v1/slides/engagement",
    response_model=SlideEngagementResponse,
    dependencies=[Depends(require_room_access(ANY_MEMBER))],
)
async def slide_engagement(request: Request, session: str = Depends(session_param)):
    """Đối chiếu timestamp câu hỏi với timestamp chuyển slide để tính số
    câu hỏi phát sinh trong lúc mỗi slide đang hiển thị — thuần tính toán
    (sort + bucket), không dùng AI (xem compute_engagement trong
    slide_store.py)."""
    slide_store: SlideEventStore = request.app.state.slide_stores.get(session)
    question_store: QuestionStore = request.app.state.question_stores.get(session)

    events = slide_store.list_all()
    question_timestamps = [q.timestamp for q in question_store.list_all()]

    slides = compute_engagement(events, question_timestamps)
    return SlideEngagementResponse(slides=slides)


# =====================================================================
# Chia sẻ file slide (PDF) cho sinh viên
# =====================================================================
# Giảng viên upload PDF (thân yêu cầu là chính file, Content-Type application/pdf) -> lưu
# theo phiên -> phát "state" cho mọi sinh viên đang nghe /ws/slides. Sinh viên tải file qua
# GET /slides/file rồi theo số trang ("page") giảng viên đang mở.
# Chỉ giảng viên của phiên upload được (core/auth.py); thành viên phiên mới tải được.

@router.post("/api/v1/slides/file", dependencies=[Depends(require_room_access(LECTURER_ONLY))])
async def upload_slide_file(request: Request, session: str = Depends(session_param)):
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_PDF_BYTES:
        raise HTTPException(status_code=413, detail="PDF quá lớn (tối đa 20 MB)")
    content = await request.body()
    if len(content) > MAX_PDF_BYTES:
        raise HTTPException(status_code=413, detail="PDF quá lớn (tối đa 20 MB)")
    if not content.startswith(b"%PDF-"):
        raise HTTPException(status_code=415, detail="Chỉ nhận file PDF")

    filename = unquote(request.headers.get("x-filename", "slides.pdf"))[:200] or "slides.pdf"
    deck: SlideDeck = request.app.state.slide_decks.get(session)
    deck.set_file(content, filename)

    manager: QAConnectionManager = request.app.state.slide_manager
    await manager.broadcast(deck.state(), session)
    return deck.state()


@router.get("/api/v1/slides/file", dependencies=[Depends(require_room_access(ANY_MEMBER))])
async def download_slide_file(request: Request, session: str = Depends(session_param)):
    deck: SlideDeck = request.app.state.slide_decks.get(session)
    if not deck.has_file:
        raise HTTPException(status_code=404, detail="Giảng viên chưa chia sẻ slide")
    return Response(
        content=deck.content,
        media_type="application/pdf",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": f"inline; filename*=UTF-8''{quote(deck.filename)}",
        },
    )


@router.get("/api/v1/slides/state", dependencies=[Depends(require_room_access(ANY_MEMBER))])
async def slide_state(request: Request, session: str = Depends(session_param)):
    return request.app.state.slide_decks.get(session).state()


@router.websocket("/api/v1/ws/slides")
async def slides_websocket(websocket: WebSocket, session: str | None = Query(None)) -> None:
    """Sinh viên CHỈ LẮNG NGHE: nhận 'state' khi vừa kết nối và khi giảng viên đổi file,
    'page' mỗi khi giảng viên chuyển slide."""
    scope = normalize_session(session)
    if scope is None:
        await websocket.close(code=1008)
        return
    manager: QAConnectionManager = websocket.app.state.slide_manager
    deck: SlideDeck = websocket.app.state.slide_decks.get(scope)

    await manager.connect(websocket, scope)
    try:
        await websocket.send_json(deck.state())
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
