"""
main.py
=======
ClassBridge Backend — điểm vào mỏng: tạo FastAPI app, cấu hình CORS và gộp
router của từng cụm. KHÔNG viết endpoint trực tiếp ở đây — mỗi cụm tự định
nghĩa endpoint trong modules/<cụm>/router.py.

Chạy:  uvicorn main:app --reload --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import logging
import os

# Chỉ giới hạn OpenBLAS để tránh lỗi cấp phát bộ nhớ ảo khi import numpy/scipy trên máy 8 GB RAM
# (không khóa OMP/MKL để CTranslate2 STT và NLLB chạy đa nhân nhanh)
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
except Exception:
    pass

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.lifespan import lifespan
from modules.live_translate.router import router as live_translate_router
from modules.qa.router import router as qa_router
from modules.question_clustering.router import router as question_clustering_router
from modules.slides.router import router as slides_router
from modules.translate.router import router as translate_router

# --- Cấu hình Logging ---
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

app = FastAPI(
    title="ClassBridge API",
    description="Hệ thống Hỗ trợ Tương tác Lớp học Song ngữ EMI thời gian thực",
    version="2.0.0",
    lifespan=lifespan,
)

# --- Cấu hình CORS để Frontend Next.js gọi được REST ---
DEFAULT_ALLOWED_ORIGINS = "http://localhost:4000,http://127.0.0.1:4000"
allowed_origins = [
    origin.strip().rstrip("/")
    for origin in os.getenv("AI_ALLOWED_ORIGINS", DEFAULT_ALLOWED_ORIGINS).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Gộp router của từng cụm ---
app.include_router(live_translate_router)
app.include_router(question_clustering_router)
app.include_router(qa_router)
app.include_router(slides_router)
app.include_router(translate_router)


@app.get("/healthz")
async def health():
    return {"status": "ok"}
