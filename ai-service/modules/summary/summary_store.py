"""
summary_store.py (modules/summary)
===================================
Kho lưu trữ bản tóm tắt bài giảng (kèm lịch sử phiên bản) và ghi chú học tập
của sinh viên theo từng phiên học. Dữ liệu được ghi bền vững xuống đĩa JSON
(`transcripts/summaries/<session>.json`) nên không bị mất khi khởi động lại
FastAPI server.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from modules.summary.schema import LessonSummaryRecord, StudentNoteOutput, StudentNoteRequest

logger = logging.getLogger("classbridge.summary_store")

_DEFAULT_SUMMARY_DIR = Path(__file__).resolve().parents[2] / "transcripts" / "summaries"


def _safe_filename(session: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_\-]", "_", session or "default")[:80] or "default"


class DiskBackedSummaryStore:
    """Lưu trữ an toàn đa luồng cho 1 phiên học, đồng bộ bền vững xuống file JSON."""

    def __init__(self, session: str = "", base_dir: Path | None = None) -> None:
        self._session = session
        self._dir = base_dir or _DEFAULT_SUMMARY_DIR
        self._lock = threading.Lock()
        self._summary: LessonSummaryRecord | None = None
        self._versions: list[dict[str, Any]] = []
        self._notes: dict[str, StudentNoteOutput] = {}
        self._loaded = False

    def _path(self) -> Path:
        return self._dir / f"{_safe_filename(self._session)}.json"

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        p = self._path()
        if not p.is_file():
            return
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            if raw.get("summary"):
                self._summary = LessonSummaryRecord(**raw["summary"])
            self._versions = list(raw.get("versions") or [])
            for n in raw.get("notes") or []:
                note = StudentNoteOutput(**n)
                self._notes[note.note_id] = note
        except Exception:
            logger.warning("Không đọc được file summary cũ %s", p, exc_info=True)

    def _persist(self) -> None:
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            payload = {
                "summary": self._summary.model_dump() if self._summary else None,
                "versions": self._versions[-20:],
                "notes": [n.model_dump() for n in self._notes.values()],
            }
            self._path().write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            logger.warning("Không ghi được file summary cho phiên '%s'", self._session, exc_info=True)

    def get_summary(self) -> LessonSummaryRecord | None:
        with self._lock:
            self._ensure_loaded()
            return self._summary

    def save_summary(self, record: LessonSummaryRecord) -> LessonSummaryRecord:
        with self._lock:
            self._ensure_loaded()
            next_version = (self._summary.version_number + 1) if self._summary else 1
            updated = record.model_copy(
                update={
                    "version_number": next_version,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            self._summary = updated
            self._versions.append(
                {
                    "version_number": next_version,
                    "updated_at": updated.updated_at,
                    "summary_data": updated.model_dump(),
                }
            )
            self._persist()
            return updated

    def list_notes(self, owner: str) -> list[StudentNoteOutput]:
        with self._lock:
            self._ensure_loaded()
            items = [n for n in self._notes.values() if n.owner == owner]
            items.sort(key=lambda x: (not x.is_pinned, x.updated_at), reverse=False)
            return sorted(items, key=lambda x: (x.is_pinned, x.updated_at), reverse=True)

    def upsert_note(self, owner: str, session_id: str, req: StudentNoteRequest) -> StudentNoteOutput:
        with self._lock:
            self._ensure_loaded()
            note_id = req.note_id if req.note_id and req.note_id in self._notes else str(uuid.uuid4())
            existing = self._notes.get(note_id)
            if existing and existing.owner != owner:
                note_id = str(uuid.uuid4())
            note = StudentNoteOutput(
                note_id=note_id,
                owner=owner,
                session_id=session_id,
                title=req.title.strip(),
                content=req.content,
                source_type=req.source_type,
                is_pinned=req.is_pinned,
                updated_at=datetime.now(timezone.utc).isoformat(),
            )
            self._notes[note_id] = note
            self._persist()
            return note

    def delete_note(self, owner: str, note_id: str) -> bool:
        with self._lock:
            self._ensure_loaded()
            existing = self._notes.get(note_id)
            if not existing or existing.owner != owner:
                return False
            del self._notes[note_id]
            self._persist()
            return True
