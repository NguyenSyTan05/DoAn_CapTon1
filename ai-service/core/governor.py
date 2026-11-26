"""
governor.py (core)
===================
Bộ điều phối thực thi (Execution Governor) & Thu thập chỉ số vận hành (Metrics):
1. Công tắc ngắt khẩn cấp động (**Kill Switch**) đọc trực tiếp từ biến môi trường
   `AI_KILL_SWITCH` hoặc tệp cờ `transcripts/kill_switch.flag` không cần deploy lại.
2. Kiểm soát hạn mức token / số lượt gọi LLM trên từng phiên học.
3. Ghi nhận độ trễ phân vị `p50 / p95 / p99`, số lượt lọc PII và số ca chặn Prompt Injection.
"""

from __future__ import annotations

import math
import os
import threading
from collections import deque
from pathlib import Path
from typing import Any

_KILL_SWITCH_FILE = Path(__file__).resolve().parent.parent / "transcripts" / "kill_switch.flag"


class ExecutionGovernor:
    def __init__(self, session_token_budget: int = 40_000) -> None:
        self._budget = max(1000, session_token_budget)
        self._lock = threading.Lock()
        self._session_tokens: dict[str, int] = {}
        self._latencies_ms: deque[float] = deque(maxlen=1000)
        self.total_requests: int = 0
        self.pii_redactions: int = 0
        self.guardrail_blocks: int = 0
        self.rate_limited_429: int = 0
        self.budget_timeouts_504: int = 0

    def is_kill_switch_active(self) -> bool:
        env_flag = os.getenv("AI_KILL_SWITCH", "0").strip().lower()
        if env_flag in ("1", "true", "on", "yes"):
            return True
        return _KILL_SWITCH_FILE.is_file()

    def check_and_consume_tokens(self, session: str, estimated_tokens: int) -> bool:
        if self.is_kill_switch_active():
            return False
        with self._lock:
            used = self._session_tokens.get(session, 0)
            if used + estimated_tokens > self._budget:
                return False
            self._session_tokens[session] = used + max(1, estimated_tokens)
            return True

    def record_latency(self, duration_ms: float) -> None:
        with self._lock:
            self.total_requests += 1
            self._latencies_ms.append(max(0.0, float(duration_ms)))

    def record_pii(self, count: int) -> None:
        if count > 0:
            with self._lock:
                self.pii_redactions += count

    def record_guardrail_block(self) -> None:
        with self._lock:
            self.guardrail_blocks += 1

    def record_429(self) -> None:
        with self._lock:
            self.rate_limited_429 += 1

    def record_504(self) -> None:
        with self._lock:
            self.budget_timeouts_504 += 1

    def snapshot(self, *, queue_depth: int = 0, batch_fill_ratio: float = 0.0) -> dict[str, Any]:
        with self._lock:
            samples = sorted(self._latencies_ms)
            total = self.total_requests
            pii = self.pii_redactions
            blocks = self.guardrail_blocks
            c429 = self.rate_limited_429
            c504 = self.budget_timeouts_504

        def _pct(p: float) -> float:
            if not samples:
                return 0.0
            idx = min(len(samples) - 1, max(0, math.ceil((p / 100.0) * len(samples)) - 1))
            return round(samples[idx], 2)

        return {
            "kill_switch_active": self.is_kill_switch_active(),
            "total_requests": total,
            "latency_ms": {
                "p50": _pct(50),
                "p95": _pct(95),
                "p99": _pct(99),
            },
            "queue_depth": queue_depth,
            "batch_fill_ratio": round(batch_fill_ratio, 4),
            "defense_counters": {
                "pii_redactions": pii,
                "guardrail_blocks": blocks,
                "backpressure_429": c429,
                "budget_timeout_504": c504,
            },
        }


governor = ExecutionGovernor()
