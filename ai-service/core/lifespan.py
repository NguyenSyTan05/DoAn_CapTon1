"""
lifespan.py (core)
====================
Vòng đời ứng dụng: nạp toàn bộ mô hình AI 1 lần khi khởi động và tạo các
store/manager dùng chung, gắn vào app.state để các router truy cập qua
request.app.state.<tên>.

Đây là nơi DUY NHẤT cần sửa khi thay InMemory*Store bằng Postgres*Store.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from core.ai import ai_service
from core.session_scope import SessionScoped
from modules.live_translate.rooms import RoomRegistry
from modules.live_translate.speech_engine import WhisperEngine
from modules.qa.answer_store import AnswerStore, InMemoryAnswerStore
from modules.qa.qa_broadcast import QAConnectionManager
from modules.qa.question_store import InMemoryQuestionStore, QuestionStore
from modules.question_clustering.semantic_question_aggregator import (
    CustomSemanticQuestionAggregator,
)
from modules.slides.deck_store import MAX_DECKS, SlideDeck
from modules.slides.slide_store import InMemorySlideEventStore, SlideEventStore

logger = logging.getLogger("classbridge.lifespan")


# --- Quản lý vòng đời (Lifespan): Tải toàn bộ model 1 lần khi khởi động ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Đang tải toàn bộ mô hình AI lên bộ nhớ...")
    try:
        # 1. Nạp STT (WhisperEngine) TRƯỚC (~1-2 giây trên CPU) để cổng 8000 sẵn sàng ngay lập tức
        engine = WhisperEngine()
        await asyncio.to_thread(engine.load)
        app.state.speech_engine = engine
        app.state.live_rooms = RoomRegistry()
        app.state.aggregator = None
        logger.info("✅ STT %s (%s/%s) đã sẵn sàng", engine.name, engine.device, engine.compute_type)

        # 2. Nạp NLLB-200 và MiniLM chạy nền để KHÔNG chặn thời gian khởi động cổng 8000
        async def _load_heavy_models_bg() -> None:
            try:
                await asyncio.to_thread(ai_service.load_models, False)
                logger.info("✅ NLLB-200 (%s) đã sẵn sàng (nền)", ai_service.device)
            except Exception as exc:  # noqa: BLE001
                logger.warning("⚠️ Không nạp được NLLB-200 (tạm chạy chế độ chỉ STT): %s", exc)

            try:
                agg = await asyncio.to_thread(CustomSemanticQuestionAggregator, translator=ai_service)
                app.state.aggregator = agg
                logger.info(
                    "✅ Semantic Question Aggregator đã sẵn sàng (Chiến lược: %s)",
                    agg.clustering_strategy_name,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("⚠️ Không nạp được MiniLM Aggregator: %s", exc)

        app.state._bg_loader_task = asyncio.create_task(_load_heavy_models_bg())

        # 3. Lecturer Answers (Q&A) store — in-memory for now (no database
        #    yet). Swappable: see modules/qa/answer_store.py docstring.
        #    [SESSION] Mỗi phiên học có kho riêng (SessionScoped); session "" = phạm vi mặc định.
        app.state.answer_stores = SessionScoped[AnswerStore](InMemoryAnswerStore)
        logger.info("Answer store sẵn sàng (theo phiên, InMemory — chưa có database)")

        # 4. Q&A broadcast — đẩy câu trả lời real-time tới mọi sinh viên
        #    đang kết nối /api/v1/ws/qa. Xem modules/qa/qa_broadcast.py.
        app.state.qa_manager = QAConnectionManager()
        logger.info("Q&A broadcast manager sẵn sàng")

        # 5. Câu hỏi sinh viên — lưu chung phía server thay vì mỗi trình
        #    duyệt tự giữ trong localStorage (khác thiết bị sẽ không bao
        #    giờ thấy câu hỏi của nhau). In-memory, chưa có database — xem
        #    modules/qa/question_store.py docstring.
        app.state.question_stores = SessionScoped[QuestionStore](InMemoryQuestionStore)
        logger.info("Question store sẵn sàng (theo phiên, InMemory — chưa có database)")

        # 6. Sự kiện chuyển slide — giảng viên tự upload PDF (SlideViewer.tsx),
        #    mỗi lần chuyển slide ghi lại timestamp để đối chiếu với câu hỏi
        #    (biểu đồ mức độ tương tác theo slide). In-memory, chưa có database.
        app.state.slide_stores = SessionScoped[SlideEventStore](InMemorySlideEventStore)
        #    [CHIA SẺ SLIDE] bộ PDF theo phiên + phát số trang cho sinh viên
        app.state.slide_decks = SessionScoped[SlideDeck](SlideDeck, max_sessions=MAX_DECKS)
        app.state.slide_manager = QAConnectionManager()
        logger.info("Slide event store sẵn sàng (theo phiên, InMemory — chưa có database)")
    except Exception as exc:
        logger.critical("LỖI KHỞI ĐỘNG: Không thể tải mô hình: %s", exc)
        raise exc

    yield

    logger.info("Đang tắt dịch vụ ClassBridge...")
    app.state.aggregator = None
    app.state.speech_engine = None
    app.state.live_rooms = None
    app.state.answer_stores = None
    app.state.qa_manager = None
    app.state.question_stores = None
    app.state.slide_stores = None
    app.state.slide_decks = None
    app.state.slide_manager = None
