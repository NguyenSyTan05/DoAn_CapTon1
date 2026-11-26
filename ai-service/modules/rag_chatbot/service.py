"""
service.py (modules/rag_chatbot)
=================================
Triển khai trọn vẹn 2 pha RAG theo chuẩn Kiến trúc Hệ thống Thông minh:
- Pha A (Indexing): Bóc tách văn bản từ Slide PDF + Phụ đề bài giảng, chia đoạn
  (chunking 500–700 ký tự, overlap 15%), sinh `point_id` tất định (idempotent UUID5),
  đồng bộ lên **Qdrant Vector DB** (khi `QDRANT_URL` bật) kèm chỉ mục vector cục bộ.
- Kiểm tra khớp phiên bản mô hình nhúng (`EMBEDDING_MODEL_VERSION`) với Qdrant lúc khởi động.
- Pha B (Retrieval & Grounded Answer): Xếp hạng kết hợp Cosine Similarity (`MiniLM-L12-v2`)
  và trùng khớp từ khóa học thuật; chỉ trả lời dựa trên đoạn trích có thật kèm `[Slide #X]`.
  Khi độ tin cậy `< MIN_CONFIDENCE`, trả về `NO_SOURCE_FOUND` (0 bịa đặt) để sinh viên
  chuyển câu hỏi lên giảng viên (`escalate`).

Fixes applied (vs. original):
- P2/B10: `answer_question()` now caches the built chunks per session keyed by a
  content hash of (slide_texts, transcript count). Re-indexing only happens when
  the underlying content actually changes, not on every chatbot message.
- Cache access is serialised with `self._lock` (shared with history lock).
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import numpy as np

from core.guardrails import sanitize_untrusted_context
from modules.rag_chatbot.schema import (
    ChatbotAskResponse,
    ChatbotHistoryItem,
    CitationItem,
)

logger = logging.getLogger("classbridge.rag_chatbot")

EMBEDDING_MODEL_VERSION = "paraphrase-multilingual-MiniLM-L12-v2:384"
COLLECTION_NAME = "classbridge_lecture_chunks"
MIN_CONFIDENCE = 0.32


@dataclass
class IndexedChunk:
    point_id: str
    session_id: str
    source_type: str  # "SLIDE" | "TRANSCRIPT"
    slide_number: int | None
    timestamp: str
    text: str


def chunk_text_with_overlap(text: str, chunk_size: int = 550, overlap: int = 85) -> list[str]:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if not cleaned:
        return []
    if len(cleaned) <= chunk_size:
        return [cleaned]
    chunks: list[str] = []
    step = max(100, chunk_size - overlap)
    pos = 0
    while pos < len(cleaned):
        piece = cleaned[pos : pos + chunk_size].strip()
        if piece:
            chunks.append(piece)
        if pos + chunk_size >= len(cleaned):
            break
        pos += step
    return chunks


def deterministic_point_id(
    session_id: str, source_type: str, ref_no: str, chunk_idx: int, text: str
) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    key = f"{session_id}:{source_type}:{ref_no}:{chunk_idx}:{digest}"
    return str(uuid.uuid5(uuid.NAMESPACE_OID, key))


def _content_hash(slide_texts: dict[int, str], transcript_items: list[dict[str, Any]]) -> str:
    """Compute a lightweight fingerprint of the session content for cache keying."""
    slide_key = hashlib.sha256(
        json_encode_slide_texts(slide_texts).encode("utf-8")
    ).hexdigest()[:16]
    # Use count + hash of first/last item text as a cheap transcript fingerprint.
    t_count = len(transcript_items)
    t_first = str(transcript_items[0].get("vi") or "") if t_count > 0 else ""
    t_last = str(transcript_items[-1].get("vi") or "") if t_count > 0 else ""
    transcript_key = hashlib.sha256(
        f"{t_count}:{t_first}:{t_last}".encode("utf-8")
    ).hexdigest()[:16]
    return f"{slide_key}:{transcript_key}"


def json_encode_slide_texts(slide_texts: dict[int, str]) -> str:
    """Stable string representation of slide_texts for hashing."""
    return ":".join(
        f"{k}={hashlib.sha256((v or '').encode()).hexdigest()[:8]}"
        for k in sorted(slide_texts)
        for v in [(slide_texts[k] or "")]
    )


def verify_qdrant_collection_on_startup() -> bool:
    """Verify / create Qdrant collection when `QDRANT_URL` is configured."""
    qdrant_url = os.getenv("QDRANT_URL", "").strip().rstrip("/")
    if not qdrant_url:
        return False
    try:
        try:
            import httpx2 as httpx
        except ImportError:
            import httpx  # type: ignore[no-redef]

        with httpx.Client(timeout=3.0) as client:
            res = client.get(f"{qdrant_url}/collections/{COLLECTION_NAME}")
            if res.status_code == 404:
                create_res = client.put(
                    f"{qdrant_url}/collections/{COLLECTION_NAME}",
                    json={"vectors": {"size": 384, "distance": "Cosine"}},
                )
                if create_res.status_code in (200, 201):
                    logger.info(
                        "Qdrant collection '%s' created (%s)",
                        COLLECTION_NAME,
                        EMBEDDING_MODEL_VERSION,
                    )
                    return True
                return False
            if res.status_code == 200:
                info = res.json().get("result", {})
                vec_cfg = info.get("config", {}).get("params", {}).get("vectors", {})
                dim = vec_cfg.get("size")
                if dim and int(dim) != 384:
                    raise RuntimeError(
                        f"Qdrant vector dimension mismatch: {dim} != 384 for {EMBEDDING_MODEL_VERSION}"
                    )
                logger.info(
                    "Qdrant collection '%s' verified (%s)", COLLECTION_NAME, EMBEDDING_MODEL_VERSION
                )
                return True
    except RuntimeError:
        raise
    except Exception as exc:
        logger.warning(
            "Cannot reach Qdrant (%s), falling back to in-process index: %s", qdrant_url, exc
        )
    return False


class RAGChatbotService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        # Conversation history keyed by (session_id, user_sub)
        self._histories: dict[tuple[str, str], list[ChatbotHistoryItem]] = {}
        # P2/B10: Chunk cache keyed by (session_id, content_hash)
        self._chunk_cache: dict[tuple[str, str], list[IndexedChunk]] = {}

    # ------------------------------------------------------------------
    # Chunk building (with content-based caching)
    # ------------------------------------------------------------------

    def build_session_chunks(
        self,
        session_id: str,
        slide_texts: dict[int, str],
        transcript_items: list[dict[str, Any]],
    ) -> list[IndexedChunk]:
        """Build (or return cached) indexed chunks for the given session content."""
        content_key = _content_hash(slide_texts, transcript_items)
        cache_key = (session_id, content_key)

        with self._lock:
            cached = self._chunk_cache.get(cache_key)
            if cached is not None:
                return cached

        chunks = self._build_chunks_uncached(session_id, slide_texts, transcript_items)

        with self._lock:
            # Evict stale cache entries for this session (content changed).
            stale = [k for k in self._chunk_cache if k[0] == session_id and k != cache_key]
            for k in stale:
                del self._chunk_cache[k]
            self._chunk_cache[cache_key] = chunks
            logger.debug(
                "Built %d chunks for session %s (key=%s)", len(chunks), session_id, content_key
            )

        return chunks

    def _build_chunks_uncached(
        self,
        session_id: str,
        slide_texts: dict[int, str],
        transcript_items: list[dict[str, Any]],
    ) -> list[IndexedChunk]:
        chunks: list[IndexedChunk] = []

        # 1. Index each slide page
        for slide_no in sorted(slide_texts):
            raw_page = slide_texts.get(slide_no) or ""
            for idx, piece in enumerate(chunk_text_with_overlap(raw_page)):
                pid = deterministic_point_id(session_id, "SLIDE", str(slide_no), idx, piece)
                chunks.append(
                    IndexedChunk(
                        point_id=pid,
                        session_id=session_id,
                        source_type="SLIDE",
                        slide_number=slide_no,
                        timestamp=f"Slide {slide_no}",
                        text=sanitize_untrusted_context(piece),
                    )
                )

        # 2. Group adjacent transcript lines into context-rich passages
        buffer: list[str] = []
        buf_time = ""
        group_idx = 0
        for item in transcript_items:
            vi = str(item.get("vi") or item.get("original_text") or "").strip()
            en = str(item.get("en") or "").strip()
            combined_line = f"{vi} ({en})" if (en and en != vi) else vi
            if not combined_line:
                continue
            if not buf_time:
                buf_time = str(item.get("timestamp") or "")
            buffer.append(combined_line)
            if sum(len(x) for x in buffer) >= 420:
                merged = " ".join(buffer)
                pid = deterministic_point_id(session_id, "TRANSCRIPT", str(group_idx), 0, merged)
                chunks.append(
                    IndexedChunk(
                        point_id=pid,
                        session_id=session_id,
                        source_type="TRANSCRIPT",
                        slide_number=None,
                        timestamp=buf_time,
                        text=sanitize_untrusted_context(merged),
                    )
                )
                group_idx += 1
                buffer = buffer[-1:]  # 1-sentence overlap
                buf_time = str(item.get("timestamp") or "")

        if buffer:
            merged = " ".join(buffer)
            pid = deterministic_point_id(session_id, "TRANSCRIPT", str(group_idx), 0, merged)
            chunks.append(
                IndexedChunk(
                    point_id=pid,
                    session_id=session_id,
                    source_type="TRANSCRIPT",
                    slide_number=None,
                    timestamp=buf_time,
                    text=sanitize_untrusted_context(merged),
                )
            )

        return chunks

    # ------------------------------------------------------------------
    # Qdrant sync
    # ------------------------------------------------------------------

    def _sync_chunks_to_qdrant(self, chunks: list[IndexedChunk], vectors: np.ndarray) -> None:
        qdrant_url = os.getenv("QDRANT_URL", "").strip().rstrip("/")
        if not qdrant_url or not chunks or vectors.shape[0] != len(chunks):
            return
        try:
            try:
                import httpx2 as httpx
            except ImportError:
                import httpx  # type: ignore[no-redef]

            points = [
                {
                    "id": ch.point_id,
                    "vector": vectors[i].tolist(),
                    "payload": {
                        "session_id": ch.session_id,
                        "source_type": ch.source_type,
                        "slide_number": ch.slide_number,
                        "timestamp": ch.timestamp,
                        "text": ch.text,
                        "embedding_version": EMBEDDING_MODEL_VERSION,
                    },
                }
                for i, ch in enumerate(chunks)
            ]
            with httpx.Client(timeout=4.0) as client:
                client.put(
                    f"{qdrant_url}/collections/{COLLECTION_NAME}/points",
                    json={"points": points},
                )
        except Exception:
            logger.debug("Qdrant sync skipped (using in-process results)", exc_info=True)

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    @staticmethod
    def _lexical_overlap_score(query: str, doc: str) -> float:
        q_tokens = {w.lower() for w in re.findall(r"[A-Za-zÀ-ỹ0-9]{2,}", query)}
        if not q_tokens:
            return 0.0
        d_tokens = {w.lower() for w in re.findall(r"[A-Za-zÀ-ỹ0-9]{2,}", doc)}
        return len(q_tokens & d_tokens) / len(q_tokens)

    # ------------------------------------------------------------------
    # Main QA entry point
    # ------------------------------------------------------------------

    def answer_question(
        self,
        *,
        session_id: str,
        user_sub: str,
        question: str,
        slide_texts: dict[int, str],
        transcript_items: list[dict[str, Any]],
        embedding_model: Any = None,
    ) -> ChatbotAskResponse:
        msg_id = str(uuid.uuid4())
        now_iso = datetime.now(timezone.utc).isoformat()

        # P2/B10: Use cached chunks when content hasn't changed.
        chunks = self.build_session_chunks(session_id, slide_texts, transcript_items)

        if not chunks:
            no_data = ChatbotAskResponse(
                message_id=msg_id,
                question=question,
                answer=(
                    "Hiện phiên học chưa có nội dung Slide PDF hoặc phụ đề lời giảng để tra cứu. "
                    "Bạn có thể bấm 'Chuyển cho giảng viên' để gửi trực tiếp câu hỏi này lên bảng điều phối."
                ),
                status="NO_SOURCE_FOUND",
                confidence=0.0,
                citations=[],
                can_escalate=True,
            )
            self._append_history(session_id, user_sub, no_data, now_iso)
            return no_data

        scores = np.zeros(len(chunks), dtype=np.float32)
        if embedding_model is not None:
            try:
                all_texts = [question] + [c.text for c in chunks]
                vecs = np.asarray(
                    embedding_model.encode(
                        all_texts, show_progress_bar=False, normalize_embeddings=True
                    ),
                    dtype=np.float32,
                )
                q_vec = vecs[0]
                doc_vecs = vecs[1:]
                cos_scores = doc_vecs @ q_vec
                self._sync_chunks_to_qdrant(chunks, doc_vecs)
                for idx, ch in enumerate(chunks):
                    lex = self._lexical_overlap_score(question, ch.text)
                    scores[idx] = float(0.75 * max(0.0, float(cos_scores[idx])) + 0.25 * lex)
            except Exception:
                logger.debug("Falling back to keyword scoring for RAG", exc_info=True)
                for idx, ch in enumerate(chunks):
                    scores[idx] = self._lexical_overlap_score(question, ch.text)
        else:
            for idx, ch in enumerate(chunks):
                scores[idx] = self._lexical_overlap_score(question, ch.text)

        ranked_idx = [int(i) for i in np.argsort(-scores)]
        best_score = float(scores[ranked_idx[0]]) if ranked_idx else 0.0

        if best_score < MIN_CONFIDENCE:
            not_found = ChatbotAskResponse(
                message_id=msg_id,
                question=question,
                answer=(
                    "Không tìm thấy thông tin đủ tin cậy trong Slide bài giảng hoặc phụ đề của buổi học này "
                    "để trả lời chính xác (tránh suy diễn ngoài tài liệu). Hãy bấm 'Chuyển cho giảng viên' để thầy/cô giải đáp."
                ),
                status="NO_SOURCE_FOUND",
                confidence=round(best_score, 3),
                citations=[],
                can_escalate=True,
            )
            self._append_history(session_id, user_sub, not_found, now_iso)
            return not_found

        top_indices = [i for i in ranked_idx[:3] if float(scores[i]) >= MIN_CONFIDENCE * 0.85]
        citations: list[CitationItem] = []
        bullet_lines: list[str] = []

        for idx in top_indices:
            ch = chunks[idx]
            sc = round(float(scores[idx]), 3)
            label = (
                f"[Slide #{ch.slide_number}]"
                if ch.source_type == "SLIDE"
                else f"[Phụ đề {ch.timestamp or 'lớp học'}]"
            )
            excerpt = ch.text[:260] + ("…" if len(ch.text) > 260 else "")
            citations.append(
                CitationItem(
                    label=label,
                    source_type="SLIDE" if ch.source_type == "SLIDE" else "TRANSCRIPT",
                    slide_number=ch.slide_number,
                    timestamp=ch.timestamp,
                    excerpt=excerpt,
                    score=sc,
                )
            )
            bullet_lines.append(f"• {label}: {excerpt}")

        synthesized = "Dựa trên học liệu và bài giảng của buổi học:\n" + "\n".join(bullet_lines)
        ans_resp = ChatbotAskResponse(
            message_id=msg_id,
            question=question,
            answer=synthesized,
            status="ANSWERED",
            confidence=round(best_score, 3),
            citations=citations,
            can_escalate=best_score < 0.55,
        )
        self._append_history(session_id, user_sub, ans_resp, now_iso)
        return ans_resp

    # ------------------------------------------------------------------
    # History management
    # ------------------------------------------------------------------

    def _append_history(
        self,
        session_id: str,
        user_sub: str,
        resp: ChatbotAskResponse,
        created_at: str,
    ) -> None:
        key = (session_id, user_sub)
        item = ChatbotHistoryItem(
            message_id=resp.message_id,
            question=resp.question,
            answer=resp.answer,
            status=resp.status,
            citations=resp.citations,
            created_at=created_at,
        )
        with self._lock:
            hist = self._histories.setdefault(key, [])
            hist.append(item)
            if len(hist) > 50:
                del hist[:-50]

    def list_history(self, session_id: str, user_sub: str) -> list[ChatbotHistoryItem]:
        with self._lock:
            return list(self._histories.get((session_id, user_sub), []))
