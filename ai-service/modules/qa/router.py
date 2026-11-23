"""
router.py (modules/qa)
========================
Q&A: câu hỏi sinh viên gửi lên (QuestionStore chung phía server), câu trả
lời của giảng viên (AnswerStore) và đẩy real-time qua WebSocket
/api/v1/ws/qa (QAConnectionManager).

Store hiện là in-memory (chưa có database); các class Postgres*Store sau
này sẽ thay vào ở core/lifespan.py mà không cần sửa các endpoint dưới đây.

Phụ thuộc chéo cụm (có chủ đích): submit_question dùng luật validate của
aggregator (modules.question_clustering) để nhất quán với /aggregate.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect

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


# =====================================================================
# Câu hỏi sinh viên
# =====================================================================
# submit_question()/list_questions() lưu chung phía server (QuestionStore),
# để câu hỏi từ MỌI thiết bị đều tới được /aggregate — không còn phụ thuộc
# localStorage riêng của từng trình duyệt.

@router.post("/api/v1/questions", response_model=QuestionInput)
async def submit_question(
    payload: QuestionInput, request: Request, session: str = Depends(session_param)
):
    """Sinh viên/giảng viên gửi MỘT câu hỏi — lưu vào QuestionStore chung.
    Dùng đúng luật validate của aggregator (text không rỗng, timestamp hợp
    lệ) để nhất quán với /aggregate. Gửi lại cùng id sẽ ghi đè (idempotent
    — an toàn nếu client retry do mất mạng)."""
    aggregator: CustomSemanticQuestionAggregator = request.app.state.aggregator
    try:
        aggregator.parse_and_validate([payload.model_dump()])
    except InvalidQuestionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    store: QuestionStore = request.app.state.question_stores.get(session)
    store.add(QuestionRecord(id=payload.id, text=payload.text, timestamp=payload.timestamp))

    return payload


@router.get("/api/v1/questions", response_model=QuestionListResponse)
async def list_questions(request: Request, session: str = Depends(session_param)):
    """Toàn bộ câu hỏi đã lưu — Dashboard/phòng live gọi cái này thay vì
    đọc localStorage, rồi POST kết quả sang /aggregate."""
    store: QuestionStore = request.app.state.question_stores.get(session)
    return QuestionListResponse(
        questions=[QuestionInput(**r.__dict__) for r in store.list_all()]
    )


@router.delete("/api/v1/questions/{question_id}")
async def remove_question(
    question_id: str, request: Request, session: str = Depends(session_param)
):
    """Dashboard gọi cái này khi xoá 1 topic — nếu không, câu hỏi đó vẫn
    còn trong QuestionStore và sẽ hồi sinh ở lần GET /api/v1/questions kế
    tiếp dù đã "xoá" khỏi localStorage cục bộ."""
    store: QuestionStore = request.app.state.question_stores.get(session)
    removed = store.remove(question_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Question not found")
    return {"status": "deleted"}


# =====================================================================
# Câu trả lời của giảng viên
# =====================================================================
# In-memory now (AnswerStore interface — see answer_store.py); swap to a
# PostgreSQL-backed implementation later without touching these endpoints
# or the frontend.

@router.post("/api/v1/answers", response_model=AnswerOutput)
async def submit_answer(
    payload: AnswerRequest, request: Request, session: str = Depends(session_param)
):
    """Giảng viên gửi (hoặc sửa) câu trả lời cho một cụm câu hỏi. Gửi lại
    cùng representative_id sẽ GHI ĐÈ câu trả lời cũ (upsert). Đẩy real-time
    qua WebSocket /api/v1/ws/qa cho mọi sinh viên đang kết nối."""
    store: AnswerStore = request.app.state.answer_stores.get(session)
    record = AnswerRecord(
        representative_id=payload.representative_id,
        representative_text=payload.representative_text,
        total_count=payload.total_count,
        answer_text=payload.answer_text,
        answered_at=datetime.now(timezone.utc).isoformat(),
    )
    store.upsert(record)
    output = AnswerOutput(**record.__dict__)

    qa_manager: QAConnectionManager = request.app.state.qa_manager
    await qa_manager.broadcast({"type": "upsert", "answer": output.model_dump()}, session)

    return output


@router.delete("/api/v1/answers/{representative_id}")
async def remove_answer(
    representative_id: str, request: Request, session: str = Depends(session_param)
):
    """Giảng viên xoá câu trả lời — đẩy real-time qua WebSocket để sinh
    viên đang xem gỡ nó khỏi màn hình ngay lập tức."""
    store: AnswerStore = request.app.state.answer_stores.get(session)
    removed = store.delete(representative_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Answer not found")

    qa_manager: QAConnectionManager = request.app.state.qa_manager
    await qa_manager.broadcast({"type": "remove", "representative_id": representative_id}, session)

    return {"status": "deleted"}


@router.get("/api/v1/answers", response_model=AnswerListResponse)
async def list_answers(request: Request, session: str = Depends(session_param)):
    """Trạng thái hiện tại — dùng cho Dashboard Giảng viên (fetch sau mỗi
    hành động) và làm fallback nếu client không dùng được WebSocket."""
    store: AnswerStore = request.app.state.answer_stores.get(session)
    return AnswerListResponse(answers=[AnswerOutput(**r.__dict__) for r in store.list_all()])


@router.websocket("/api/v1/ws/qa")
async def qa_websocket(websocket: WebSocket, session: str | None = Query(None)) -> None:
    """Sinh viên kết nối và CHỈ LẮNG NGHE — không gửi gì lên. Ngay khi kết
    nối, nhận một 'snapshot' của toàn bộ câu trả lời hiện có (để không bỏ
    lỡ những câu đã được trả lời trước khi họ vào phòng); sau đó nhận các
    sự kiện 'upsert' / 'remove' theo thời gian thực khi giảng viên thao tác."""
    scope = normalize_session(session)
    if scope is None:
        await websocket.close(code=1008)  # session sai định dạng
        return

    manager: QAConnectionManager = websocket.app.state.qa_manager
    store: AnswerStore = websocket.app.state.answer_stores.get(scope)

    await manager.connect(websocket, scope)
    try:
        snapshot = [AnswerOutput(**r.__dict__).model_dump() for r in store.list_all()]
        await websocket.send_json({"type": "snapshot", "answers": snapshot})

        while True:
            # Sinh viên không gửi gì lên — receive_text() chỉ dùng để phát
            # hiện lúc client ngắt kết nối (giống hệt live_translate()).
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
