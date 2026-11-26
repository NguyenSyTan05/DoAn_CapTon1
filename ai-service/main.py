"""
main.py
=======
ClassBridge AI Backend — điểm vào FastAPI: cấu hình CORS (hỗ trợ mạng LAN),
middleware đo độ trễ `p50/p95/p99`, endpoint `/api/v1/metrics` và gộp tất cả
các router nghiệp vụ (Live Translate, Q&A, Gom cụm, Slide, Tóm tắt AI, RAG Chatbot).
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
except Exception:
    pass

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from core.governor import governor
from core.lifespan import lifespan
from modules.live_translate.router import router as live_translate_router
from modules.qa.router import router as qa_router
from modules.question_clustering.router import router as question_clustering_router
from modules.rag_chatbot.router import router as rag_chatbot_router
from modules.slides.router import router as slides_router
from modules.summary.router import router as summary_router
from modules.translate.router import router as translate_router

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

app = FastAPI(
    title="ClassBridge API",
    description="Hệ thống Hỗ trợ Tương tác Lớp học Song ngữ EMI thời gian thực",
    version="2.1.0",
    lifespan=lifespan,
)

DEFAULT_ALLOWED_ORIGINS = "http://localhost:4000,http://127.0.0.1:4000"
allowed_origins = [
    origin.strip().rstrip("/")
    for origin in os.getenv("AI_ALLOWED_ORIGINS", DEFAULT_ALLOWED_ORIGINS).split(",")
    if origin.strip()
]
allow_lan_regex = (
    r"^https?://(localhost|127\.0\.0\.1|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
    r"192\.168\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3})(:\d+)?$"
    if os.getenv("AI_ALLOW_LAN_ORIGINS", "1").strip().lower() in ("1", "true", "yes")
    else None
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=allow_lan_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def track_request_latency(request: Request, call_next):
    t0 = time.perf_counter()
    response = await call_next(request)
    governor.record_latency((time.perf_counter() - t0) * 1000.0)
    return response


app.include_router(live_translate_router)
app.include_router(question_clustering_router)
app.include_router(qa_router)
app.include_router(slides_router)
app.include_router(summary_router)
app.include_router(rag_chatbot_router)
app.include_router(translate_router)


@app.get("/healthz")
async def health():
    return {"status": "ok"}


@app.get("/api/v1/metrics")
async def runtime_metrics(request: Request):
    batcher = getattr(request.app.state, "embedding_batcher", None)
    q_depth = batcher.queue_depth if batcher is not None else 0
    fill = batcher.batch_fill_ratio if batcher is not None else 0.0
    return governor.snapshot(queue_depth=q_depth, batch_fill_ratio=fill)
