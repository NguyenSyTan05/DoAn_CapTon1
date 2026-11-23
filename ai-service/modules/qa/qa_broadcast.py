"""
qa_broadcast.py
================
[CUSTOM] In-memory WebSocket broadcast registry for the Q&A feature.

The existing /api/v1/ws/live-translate endpoint (main.py) is a private
per-connection pipe — it only ever sends back to the same client that sent
audio, there is no concept of "broadcast to everyone". Pushing a lecturer's
answer to every connected student needs that broadcast concept, so this is
a separate, dedicated manager rather than overloading the audio socket.

[SESSION] Kết nối được nhóm theo `session` (phiên học): câu trả lời của một
phiên chỉ được đẩy tới sinh viên đang ở đúng phiên đó. session "" = phạm vi
mặc định (hành vi cũ: một phòng chung).

Kept out of answer_store.py on purpose: AnswerStore is about *persistence*
(swappable for PostgreSQL later); this is about *live delivery* to whoever
is currently connected, which stays in-process regardless of what storage
backs AnswerStore.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger("classbridge.qa_broadcast")


class QAConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, session: str = "") -> None:
        await websocket.accept()
        self._connections.setdefault(session, []).append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        for session, connections in list(self._connections.items()):
            if websocket in connections:
                connections.remove(websocket)
            if not connections:
                del self._connections[session]

    def count(self, session: str = "") -> int:
        return len(self._connections.get(session, []))

    async def broadcast(self, message: dict[str, Any], session: str = "") -> None:
        """Send to every client connected to `session`. A client that fails to
        receive (already gone but not yet cleaned up) is dropped instead of
        breaking the broadcast for everyone else."""
        stale: list[WebSocket] = []
        for connection in list(self._connections.get(session, [])):
            try:
                await connection.send_json(message)
            except Exception:
                stale.append(connection)
        for connection in stale:
            self.disconnect(connection)
