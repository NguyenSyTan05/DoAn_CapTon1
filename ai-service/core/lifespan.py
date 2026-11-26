"""
lifespan.py (core)
====================
Vòng đời ứng dụng: nạp toàn bộ mô hình AI 1 lần khi khởi động, kiểm tra khớp
phiên bản Qdrant (nếu bật), khởi chạy `DynamicBatcher`, và gắn toàn bộ các kho
dữ liệu (hỗ trợ chuyển đổi `memory` / `postgres` qua `AI_STORAGE_BACKEND`) vào `app.state`.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from core import auth
from core.ai import ai_service
from core.batcher import DynamicBatcher
from core.pg_stores import (
    build_answer_store,
    build_question_store,
    build_slide_store,
    build_summary_store,
)
from core.session_scope import SessionScoped
from modules.live_translate.rooms import RoomRegistry
from modules.live_translate.speech_engine import WhisperEngine
from modules.qa.answer_store import AnswerStore
from modules.qa.qa_broadcast import QAConnectionManager
from modules.qa.question_store import QuestionStore
from modules.rag_chatbot.service import RAGChatbotService, verify_qdrant_collection_on_startup
from modules.slides.deck_store import MAX_DECKS, SlideDeck
from modules.slides.slide_store import SlideEventStore
from modules.summary.summary_store import DiskBackedSummaryStore

logger = logging.getLogger("classbridge.lifespan")


@asynccontextmanager
async def lifespan(app: FastAPI):
    auth.reload_settings()
    auth.validate_settings()
    logger.info("Đang tải toàn bộ mô hình AI lên bộ nhớ...")
    batcher: DynamicBatcher | None = None
    try:
        # 1. Nạp NLLB-200 trên CUDA TRƯỚC khi khởi tạo CTranslate2 WhisperEngine
        try:
            await asyncio.to_thread(ai_service.load_models, False)
            logger.info("✅ NLLB-200 (%s) đã sẵn sàng", ai_service.device)
        except Exception as exc:  # noqa: BLE001
            logger.warning("⚠️ Không nạp được NLLB-200 (tạm chạy chế độ chỉ STT): %s", exc)

        # 2. Nạp STT (WhisperEngine)
        engine = WhisperEngine()
        await asyncio.to_thread(engine.load)
        app.state.speech_engine = engine
        app.state.live_rooms = RoomRegistry()
        app.state.aggregator = None
        logger.info("✅ STT %s (%s/%s) đã sẵn sàng", engine.name, engine.device, engine.compute_type)

        # 3. Nạp MiniLM trên CPU & khởi chạy DynamicBatcher
        from modules.question_clustering.semantic_question_aggregator import (
            CustomSemanticQuestionAggregator,
        )

        aggregator = await asyncio.to_thread(
            CustomSemanticQuestionAggregator, device="cpu", translator=ai_service
        )
        app.state.aggregator = aggregator
        batcher = DynamicBatcher(aggregator.encode_questions)
        await batcher.start()
        app.state.embedding_batcher = batcher
        logger.info(
            "✅ Semantic Question Aggregator & DynamicBatcher đã sẵn sàng (Chiến lược: %s)",
            aggregator.clustering_strategy_name,
        )

        # 4. Kiểm tra Qdrant Vector DB (nếu QDRANT_URL được cấu hình) & khởi tạo RAG Service
        await asyncio.to_thread(verify_qdrant_collection_on_startup)
        app.state.rag_service = RAGChatbotService()
        logger.info("✅ RAG Chatbot Service đã sẵn sàng")

        # 5. Khởi tạo các Store theo phiên (hỗ trợ cả InMemory lẫn PostgreSQL qua AI_STORAGE_BACKEND)
        app.state.answer_stores = SessionScoped[AnswerStore](build_answer_store, pass_session=True)
        app.state.qa_manager = QAConnectionManager()
        app.state.question_stores = SessionScoped[QuestionStore](build_question_store, pass_session=True)
        app.state.slide_stores = SessionScoped[SlideEventStore](build_slide_store, pass_session=True)
        app.state.slide_decks = SessionScoped[SlideDeck](SlideDeck, max_sessions=MAX_DECKS)
        app.state.slide_manager = QAConnectionManager()
        app.state.summary_stores = SessionScoped[DiskBackedSummaryStore](
            build_summary_store, pass_session=True
        )
        logger.info("✅ Toàn bộ Session Stores đã sẵn sàng")
    except Exception as exc:
        logger.critical("LỖI KHỞI ĐỘNG: Không thể tải mô hình: %s", exc)
        raise exc

    yield

    logger.info("Đang tắt dịch vụ ClassBridge...")
    if batcher is not None:
        await batcher.stop()
    app.state.embedding_batcher = None
    app.state.rag_service = None
    app.state.aggregator = None
    app.state.speech_engine = None
    app.state.live_rooms = None
    app.state.answer_stores = None
    app.state.qa_manager = None
    app.state.question_stores = None
    app.state.slide_stores = None
    app.state.slide_decks = None
    app.state.slide_manager = None
    app.state.summary_stores = None
