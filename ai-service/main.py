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

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import Response
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
    r"192\.168\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}|"
    r"[a-zA-Z0-9-]+(\.[a-zA-Z0-9-]+)*\.(vercel\.app|trycloudflare\.com))(:\d+)?$"
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


@app.get("/")
async def gateway_root():
    return {"service": "ClassBridge Unified Gateway", "status": "ok"}


@app.get("/healthz")
async def health():
    return {"status": "ok"}


@app.get("/api/v1/metrics")
async def runtime_metrics(request: Request):
    batcher = getattr(request.app.state, "embedding_batcher", None)
    q_depth = batcher.queue_depth if batcher is not None else 0
    fill = batcher.batch_fill_ratio if batcher is not None else 0.0
    return governor.snapshot(queue_depth=q_depth, batch_fill_ratio=fill)


# ---------------------------------------------------------------------------
# Unified Cloud Gateway Proxy -> Flask Backend (:5000)
# Cho phép mở duy nhất 1 cổng HTTPS Cloudflare Tunnel (cổng 8000) phục vụ đồng thời
# cả REST/WebSocket AI (/api/v1/*, /ws/*) lẫn toàn bộ API Flask (/auth/*, /giang-vien/*).
# ---------------------------------------------------------------------------
_HOP_BY_HOP_HEADERS = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "content-encoding",
        "content-length",
        "host",
    }
)


async def _forward_to_flask(target_path: str, request: Request) -> Response:
    flask_base = os.getenv("FLASK_API_URL", "http://127.0.0.1:5000").rstrip("/")
    query = f"?{request.url.query}" if request.url.query else ""
    target_url = f"{flask_base}/{target_path.lstrip('/')}{query}"

    fwd_headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in _HOP_BY_HOP_HEADERS and not k.lower().startswith("origin")
    }
    client_host = (
        request.headers.get("cf-connecting-ip")
        or (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
        or (request.client.host if request.client else "")
    )
    if client_host:
        fwd_headers["X-Forwarded-For"] = client_host
        fwd_headers["X-Real-IP"] = client_host
    body = await request.body()

    async with httpx.AsyncClient(timeout=30.0) as client:
        upstream = await client.request(
            method=request.method,
            url=target_url,
            headers=fwd_headers,
            content=body,
        )

    resp_headers = {
        k: v
        for k, v in upstream.headers.items()
        if k.lower() not in _HOP_BY_HOP_HEADERS
        and not k.lower().startswith("access-control-")
        and k.lower() != "vary"
    }
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=resp_headers,
        media_type=upstream.headers.get("content-type"),
    )


_PROXY_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


@app.api_route("/auth", methods=_PROXY_METHODS, include_in_schema=False)
@app.api_route("/auth/{subpath:path}", methods=_PROXY_METHODS, include_in_schema=False)
async def proxy_auth(request: Request, subpath: str = "") -> Response:
    return await _forward_to_flask(f"auth/{subpath}" if subpath else "auth", request)


@app.api_route("/giang-vien", methods=_PROXY_METHODS, include_in_schema=False)
@app.api_route("/giang-vien/{subpath:path}", methods=_PROXY_METHODS, include_in_schema=False)
async def proxy_lecturer(request: Request, subpath: str = "") -> Response:
    return await _forward_to_flask(f"giang-vien/{subpath}" if subpath else "giang-vien", request)


@app.api_route("/health", methods=["GET"], include_in_schema=False)
async def proxy_flask_health(request: Request) -> Response:
    return await _forward_to_flask("health", request)


@app.api_route("/ready", methods=["GET"], include_in_schema=False)
async def proxy_flask_ready(request: Request) -> Response:
    return await _forward_to_flask("ready", request)
