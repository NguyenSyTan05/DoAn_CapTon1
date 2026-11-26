# ClassBridge

> **AI-powered bilingual (EN ↔ VI) classroom platform for EMI (English-Medium Instruction) courses.**

ClassBridge provides live lecture transcription, real-time translation, semantic Q&A clustering, RAG-based chatbot, and a lesson-summary engine. Three roles are supported: **Admin**, **Giảng viên (Lecturer)**, and **Sinh viên (Student)**.

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Prerequisites](#prerequisites)
4. [Installation & Configuration](#installation--configuration)
5. [Usage](#usage)
6. [API Reference](#api-reference)
7. [Troubleshooting](#troubleshooting)

---

## Overview

| Feature | Description |
|---------|-------------|
| Live transcription | Whisper (CTranslate2) converts lecturer audio to text in real time |
| EN ↔ VI translation | NLLB-200 (ctranslate2) translates every utterance bidirectionally |
| Semantic Q&A clustering | MiniLM-L12-v2 embeds student questions; DBSCAN groups duplicates |
| RAG chatbot | Students ask about slide content; MiniLM + Qdrant retrieves grounded answers |
| Lesson summary | Hybrid extractive + optional LLM overview with comprehension heatmap |
| Audit log | Every API request is recorded in `audit_logs` with actor role, IP, and JSONB details |

### Tech Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| Backend API | Python + Flask + Flask-JWT-Extended + Flask-SQLAlchemy | Python ≥ 3.11, Flask ≥ 3.0 |
| AI Service | Python + FastAPI + Uvicorn | Python ≥ 3.11, FastAPI ≥ 0.115 |
| Database | PostgreSQL | ≥ 15 |
| Vector DB | Qdrant | ≥ 1.12 |
| Whisper runtime | CTranslate2 | ≥ 4.x |
| Translation | NLLB-200 via ctranslate2 | — |
| Embedding | sentence-transformers MiniLM-L12-v2 | — |
| Frontend | React + TypeScript | Node.js ≥ 18 |

---

## Architecture

### Directory Tree

```
DemoMidTerm-master/
├── backend/                   # Flask REST API
│   ├── app.py                 # Application factory, CORS, health probes
│   ├── config.py              # Environment config (validated at import time)
│   ├── extensions.py          # SQLAlchemy db instance
│   ├── audit_service.py       # Per-request audit logging
│   ├── request_limits.py      # In-process sliding-window rate limiter
│   ├── verification_service.py# OTP & password-reset tokens
│   ├── email_utils.py         # Email format + optional API validation
│   ├── routes/
│   │   ├── login.py           # POST /auth/login  POST /auth/logout
│   │   ├── password_management.py  # Change / forgot / reset password
│   │   ├── session_access.py  # Session join / leave
│   │   └── ...                # Other route blueprints
│   └── .env                   # Backend environment variables (not committed)
│
├── ai-service/                # FastAPI AI micro-service
│   ├── main.py                # FastAPI app + router registration
│   ├── core/
│   │   ├── ai.py              # AiService singleton (loads all models)
│   │   ├── auth.py            # JWT + room-access middleware
│   │   ├── batcher.py         # DynamicBatcher (async embedding batching)
│   │   ├── guardrails.py      # Prompt-injection sanitizer
│   │   ├── governor.py        # 429/504 counters
│   │   └── lifespan.py        # FastAPI startup/shutdown (model loading)
│   ├── modules/
│   │   ├── summary/           # Lesson summary generator
│   │   ├── question_clustering/  # Semantic question aggregator
│   │   ├── rag_chatbot/       # RAG chatbot (Qdrant + MiniLM)
│   │   ├── live_translate/    # WebSocket live translation
│   │   └── slides/            # Slide PDF extraction & heatmap
│   ├── transcripts/           # Per-session JSONL transcript files
│   └── .env                   # AI service environment variables (not committed)
│
├── frontend/                  # React + TypeScript SPA
│   ├── src/
│   └── package.json
│
└── db.sql                     # Complete PostgreSQL schema (25+ tables)
```

### Data Flow

```
Student (Browser)
      │  HTTP/WS
      ▼
React Frontend (port 4000)
      │  REST / WebSocket
      ▼
Flask Backend  (port 5000)
  ├── JWT auth (HS256, shared SECRET_KEY)
  ├── audit_logs  ──────────────────► PostgreSQL
  └── Proxy AI requests
              │  HTTP / WebSocket
              ▼
        FastAPI AI Service  (port 8000)
          ├── Whisper  → transcript JSONL
          ├── NLLB-200 → translated text
          ├── MiniLM   → embeddings
          └── Qdrant   → vector search  ◄──► Qdrant (port 6333)
```

---

## Prerequisites

| Requirement | Minimum Version | Notes |
|-------------|----------------|-------|
| Python | 3.11 | Backend + AI service |
| Node.js | 18 LTS | Frontend build |
| PostgreSQL | 15 | With `pgcrypto` extension |
| Docker | 24+ | Recommended for Qdrant; native install also works |
| CUDA (optional) | 12.x | GPU acceleration for Whisper / NLLB |
| Git | any | Source checkout |

> **Note:** Whisper and NLLB-200 models are downloaded automatically on first run. Plan for ~3–5 GB of model storage.

---

## Installation & Configuration

### 1. Clone & enter project root

```bash
git clone <repo-url> classbridge
cd classbridge/DemoMidTerm-master
```

### 2. Start Qdrant (Docker)

```bash
docker compose up -d
# or manually:
docker run -d --name qdrant -p 6333:6333 -p 6334:6334 qdrant/qdrant:latest
```

### 3. Create the PostgreSQL database

```bash
psql -U postgres -c "CREATE DATABASE classbridge;"
psql -U postgres -d classbridge -f db.sql
```

### 4. Backend setup

```bash
cd backend
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env   # then edit — see table below
```

#### Backend `.env` variables

| Variable | Required | Default | Example / Notes |
|----------|----------|---------|-----------------|
| `DATABASE_URL` | ✅ | — | `postgresql://postgres:secret@localhost:5432/classbridge` |
| `SECRET_KEY` | ✅ | — | Min 32 chars. Generate: `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `FRONTEND_ORIGIN` | — | `http://localhost:4000` | Comma-separated for multiple origins |
| `ALLOW_LAN_ORIGINS` | — | `0` | Set `1` to allow RFC1918 LAN IPs (e.g. for mobile dev) |
| `SMTP_HOST` | — | — | `smtp.gmail.com` |
| `SMTP_PORT` | — | `587` | `587` (STARTTLS) or `465` (SSL) |
| `SMTP_USERNAME` | — | — | Your SMTP login |
| `SMTP_PASSWORD` | — | — | App-specific password recommended |
| `SMTP_FROM` | — | — | `ClassBridge <noreply@example.com>` |
| `SMTP_USE_TLS` | — | `true` | `true` / `false` |
| `EMAIL_VALIDATION_API_KEY` | — | — | AbstractAPI key for real-time email validation |
| `ADMIN_TOKEN_HOURS` | — | `1` | JWT lifetime for admin role (hours) |
| `LECTURER_TOKEN_HOURS` | — | `8` | JWT lifetime for lecturer role (hours) |
| `STUDENT_TOKEN_HOURS` | — | `4` | JWT lifetime for student role (hours) |
| `LOG_LEVEL` | — | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |

### 5. AI Service setup

```bash
cd ../ai-service
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
# Verify PyJWT is installed (required for JWT middleware)
python -c "import jwt; print(jwt.__version__)"
cp .env.example .env   # then edit — see table below
```

> **Important (Windows):** If `import jwt` fails, install it manually:
> ```powershell
> ai-service\.venv\Scripts\pip.exe install "PyJWT>=2.8,<3.0"
> ```

#### AI Service `.env` variables

| Variable | Required | Default | Example / Notes |
|----------|----------|---------|-----------------|
| `SECRET_KEY` | ✅ | — | **Must match** backend `SECRET_KEY` exactly |
| `FLASK_API_URL` | ✅ | — | `http://localhost:5000` |
| `AI_AUTH_MODE` | — | `jwt` | `jwt` or `internal` |
| `QDRANT_URL` | — | — | `http://localhost:6333` — omit to disable Qdrant |
| `AI_STORAGE_BACKEND` | — | `local` | `local` or `s3` |
| `SUMMARY_LLM_BASE_URL` | — | — | `http://127.0.0.1:11434/v1` (Ollama) for LLM-enhanced summaries |
| `SUMMARY_LLM_MODEL` | — | `qwen2.5:7b` | Any OpenAI-compatible model name |
| `SUMMARY_LLM_API_KEY` | — | `ollama` | API key for external LLM provider |
| `LOG_LEVEL` | — | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |

### 6. Frontend setup

```bash
cd ../frontend
npm install
cp .env.example .env.local
# Set VITE_API_URL=http://localhost:5000
# Set VITE_AI_URL=http://localhost:8000
```

---

## Usage

### Development

```bash
# Terminal 1 — Backend
cd backend && source .venv/bin/activate
flask run --port 5000 --debug

# Terminal 2 — AI Service
cd ai-service && source .venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 3 — Frontend
cd frontend && npm run dev
```

### Production

```bash
# Backend (Gunicorn — 4 sync workers)
cd backend
gunicorn -w 4 -b 0.0.0.0:5000 "app:app"

# AI Service (Uvicorn — 2 workers; keep low due to in-memory model state)
cd ai-service
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 2

# Frontend — build static assets, serve with Nginx / CDN
cd frontend && npm run build
```

> **Important:** The backend rate-limiter is **process-local**. Under multi-worker Gunicorn, each worker maintains an independent counter. For production multi-worker deployments, replace with a Redis-backed limiter.

### Testing

```bash
cd backend  && pytest tests/ -v
cd ai-service && pytest tests/ -v
cd frontend && npm run test
```

---

## API Reference

### Backend — Auth

#### `POST /auth/login`

**Request**
```json
{ "login": "user@example.com", "password": "s3cur3P@ss" }
```

**Response `200`**
```json
{
  "success": true,
  "access_token": "eyJ...",
  "user": { "id": "uuid", "email": "user@example.com", "full_name": "Nguyễn Văn A", "role": "sinh_vien" }
}
```

**Response `401`** `{ "success": false, "message": "Sai thông tin đăng nhập hoặc tài khoản chưa kích hoạt." }`

---

#### `POST /auth/logout`
**Headers:** `Authorization: Bearer <token>`  
**Response `200`** `{ "success": true, "message": "Đã đăng xuất." }`

---

#### `POST /auth/change-password`
**Headers:** `Authorization: Bearer <token>`  
**Request** `{ "current_password": "old", "new_password": "newStr0ng!" }`  
**Response `200`** `{ "success": true, "message": "Mật khẩu đã được cập nhật." }`

---

#### `POST /auth/password/forgot/send`
**Request** `{ "email": "user@example.com" }`  
**Response `200`** `{ "success": true, "message": "OTP đã được gửi đến email." }`

---

#### `POST /auth/password/forgot/verify`
**Request** `{ "email": "user@example.com", "otp": "1234" }`  
**Response `200`** `{ "success": true, "reset_token": "uuid" }`

---

#### `POST /auth/password/forgot/reset`
**Request** `{ "reset_token": "uuid", "new_password": "newStr0ng!" }`  
**Response `200`** `{ "success": true, "message": "Mật khẩu đã được đặt lại thành công." }`

---

#### `GET /health` — Liveness probe  
**Response `200`** `{ "status": "ok" }`

#### `GET /ready` — Readiness probe (checks DB)  
**Response `200`** `{ "status": "ready", "db": "ok" }`  
**Response `503`** `{ "status": "not_ready", "db": "unreachable" }`

---

### AI Service — Summary

#### `POST /api/summary/generate`
**Headers:** `Authorization: Bearer <token>`

**Request**
```json
{
  "session_id": "uuid",
  "lesson_title": "Deadlock & Starvation",
  "lecturer_notes": "Nhấn mạnh ví dụ dining philosophers"
}
```

**Response `200`** — `LessonSummaryRecord` with fields: `session_id`, `lesson_title`, `overview`, `overview_en`, `lecture_structure[]`, `key_concepts[]`, `vocabulary[]`, `examples[]`, `key_takeaways[]`, `further_clarification[]`, `heatmap[]`, `generation_status`, `updated_at`.

---

### AI Service — Q&A Clustering

#### `POST /api/clustering/aggregate`

**Request**
```json
{
  "session_id": "uuid",
  "questions": [
    { "id": "q1", "text": "Deadlock là gì?", "timestamp": "00:12:30" },
    { "id": "q2", "text": "Bế tắc xảy ra khi nào?", "timestamp": "00:12:45" }
  ]
}
```

**Response `200`**
```json
{
  "clusters": [
    { "representative_id": "q1", "representative_text": "Deadlock là gì?", "total_count": 2, "member_ids": ["q1","q2"] }
  ]
}
```

---

### AI Service — RAG Chatbot

#### `POST /api/chatbot/ask`

**Request**
```json
{
  "session_id": "uuid",
  "question": "Điều kiện nào dẫn đến deadlock?",
  "slide_texts": { "1": "...", "3": "..." },
  "transcript_items": [{ "vi": "...", "en": "...", "timestamp": "00:05:00" }]
}
```

**Response `200`**
```json
{
  "message_id": "uuid",
  "answer": "Dựa trên học liệu...\n• [Slide #3]: ...",
  "status": "ANSWERED",
  "confidence": 0.72,
  "citations": [{ "label": "[Slide #3]", "source_type": "SLIDE", "slide_number": 3, "excerpt": "...", "score": 0.72 }],
  "can_escalate": false
}
```

---

### AI Service — Live Translation (WebSocket)

#### `WS /ws/live-translate/{session_id}`

Send raw 16-bit PCM audio at 16 kHz mono (binary frames).  
Receive JSON translation segments:
```json
{
  "segment_id": "uuid",
  "original_text": "Let's look at the first condition...",
  "source_lang": "en",
  "translated_text": "Hãy xem xét điều kiện đầu tiên...",
  "timestamp": "00:03:17"
}
```

---

## Troubleshooting

### `RuntimeError: DATABASE_URL is not set`
**Fix:** Add `DATABASE_URL=postgresql://user:pass@localhost:5432/classbridge` to `backend/.env`.

---

### `RuntimeError: Thiếu hoặc SECRET_KEY quá ngắn`
**Fix:**
```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
# Paste output as SECRET_KEY in backend/.env AND ai-service/.env (must match)
```

---

### `smtplib.SMTPAuthenticationError` on password-reset emails
**Fix:** Use an app-specific password (Gmail → Account → Security → App passwords). Check `SMTP_HOST`, `SMTP_PORT`, `SMTP_USE_TLS` in `.env.email`.

---

### `RuntimeError: Qdrant vector dimension mismatch`
**Fix:** Delete and recreate the collection:
```bash
curl -X DELETE http://localhost:6333/collections/classbridge_lecture_chunks
# Restart ai-service — it recreates the collection automatically.
```

---

### `ModuleNotFoundError: No module named 'ctranslate2'`
**Fix:**
```bash
pip install ctranslate2           # CPU-only
# CUDA 12:
pip install ctranslate2 --extra-index-url https://download.pytorch.org/whl/cu121
```

---

### Backend returns `500` after first login attempt
**Cause:** `audit_logs` table missing or insufficient DB privileges.  
**Fix:**
```bash
psql -U postgres -d classbridge -f db.sql
psql -U postgres -d classbridge -c "GRANT INSERT ON audit_logs TO <app_user>;"
```

---

### Rate-limit 429 hit immediately on dev machine
**Fix:** Increase `MAX_REQUESTS` / `WINDOW_SECONDS` in `backend/request_limits.py` for local development, or ensure each client sends a distinct `X-Real-IP` header.

---

### `psycopg2.OperationalError: could not connect to server`
**Fix:** Verify PostgreSQL is running and `DATABASE_URL` host/port/credentials are correct:
```bash
pg_ctl status -D /path/to/data   # Linux/macOS
# Windows: check Services → postgresql-x64-15
```

---

### `ModuleNotFoundError: No module named 'jwt'` (AI Service)
**Cause:** `PyJWT` was not installed into the AI-service virtual environment even though it is in `requirements.txt`.  
**Fix:**
```powershell
# Windows — run from project root
ai-service\.venv\Scripts\pip.exe install "PyJWT>=2.8,<3.0"
# Then re-verify:
ai-service\.venv\Scripts\python.exe -c "import jwt; print(jwt.__version__)"
```
```bash
# macOS / Linux
ai-service/.venv/bin/pip install "PyJWT>=2.8,<3.0"
```

---

### AI Service starts but `DynamicBatcher` worker never runs
**Cause (historical):** `batcher.start()` was an `async` coroutine but was called without `await` in `core/lifespan.py` — the coroutine was silently dropped.  
**Status:** ✅ Fixed in current codebase (`await batcher.start()` on line 72 of `core/lifespan.py`).  
If you still see the symptom after a Git pull, verify: `grep -n "batcher.start" ai-service/core/lifespan.py` should show `await batcher.start()`.

---

### `start-all.ps1` — Flask starts with AI-service GPU Python (Windows)
**Cause (historical):** The launcher used one `$PythonExe` for both services; it resolved to the AI-service `.venv` Python which may lack Flask deps.  
**Status:** ✅ Fixed — `start-all.ps1` now uses `$BackendPythonExe` for Flask and `$AiPythonExe` for the AI service.  
Override individual Pythons via environment variables before running:
```powershell
$env:CLASSBRIDGE_BACKEND_PYTHON = "C:\Python311\python.exe"
$env:CLASSBRIDGE_AI_PYTHON      = "D:\...\ai-service\.venv\Scripts\python.exe"
.\start-all.ps1
```

---

### Upload slide returns `500` / `null value in column "mime_type"`
**Cause (historical):** `mimetypes.guess_type()` returned `None` for some Office file extensions; the value was inserted directly into a NOT NULL column.  
**Status:** ✅ Fixed — unknown MIME types now fall back to `application/octet-stream`.

---

### `POST /auth/activity` returns `500` on every click event
**Cause (historical):** `routes/activity.py` inserted into `audit_logs` with columns `actor_email`, `entity_name`, and `status` — which do not exist in the schema (see `db.sql`).  
**Status:** ✅ Fixed — those values are now packed into the `details JSONB` column. The INSERT now only references real schema columns.

---

### `POST /auth/student/classes/join` returns `500` after joining class
**Cause (historical):** `routes/student_classes.py` `_audit()` inserted into `audit_logs` with columns `actor_email`, `entity_name`, and `status` — which do not exist in the schema.  
**Status:** ✅ Fixed — email and class name are packed into `details JSONB`; INSERT uses only valid columns.

---

### Admin logs page shows blank emails / "Hệ thống" for all entries
**Cause (historical):** `routes/admin/ghilog.py` searched `audit_logs.actor_email`, `audit_logs.entity_name`, and `audit_logs.session_id` in its COALESCE filter — all non-existent columns that caused PostgreSQL errors on search.  
**Status:** ✅ Fixed — search COALESCE now references only real columns; serializer falls back to joined-table emails (`admin_actor_email`, etc.) and reads `actor_email` / `class_name` from the `details JSONB` field when available.
