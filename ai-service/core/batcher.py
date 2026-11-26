"""
batcher.py (core)
==================
1. `DynamicBatcher`: Gom lô các truy vấn nhúng vector (MiniLM) bất đồng bộ qua
   `asyncio.Queue` với `max_batch_size`, `max_wait_ms` và `max_queue_size`.
   - Khi hàng đợi chạm trần -> trả `HTTP 429` kèm header `Retry-After` (Backpressure).
   - Khi vượt ngân sách thời gian `budget_ms` -> trả `HTTP 504` (Latency Budget).
2. `IdempotencyStore`: Lưu kết quả theo `Idempotency-Key` (LRU + TTL) để chống xử lý
   trùng lặp khi mạng di động chập chờn gửi lại yêu cầu.

Fixes applied (vs. original):
- B12: start() had a race condition — two concurrent callers could both see
  `_worker_task.done()` and create two worker loops. Fixed with an asyncio.Lock
  (`_start_lock`) guarding the check-and-create block.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np
from fastapi import HTTPException, Request

from core.governor import governor

logger = logging.getLogger("classbridge.batcher")


@dataclass
class _BatchJob:
    texts: list[str]
    future: asyncio.Future[np.ndarray]


class DynamicBatcher:
    def __init__(
        self,
        encode_fn: Callable[[list[str]], np.ndarray],
        *,
        max_batch_size: int = 16,
        max_wait_ms: float = 25.0,
        max_queue_size: int = 128,
    ) -> None:
        self._encode_fn = encode_fn
        self.max_batch_size = max(1, max_batch_size)
        self.max_wait_s = max(0.001, max_wait_ms / 1000.0)
        self.max_queue_size = max(4, max_queue_size)
        self._queue: asyncio.Queue[_BatchJob] | None = None
        self._worker_task: asyncio.Task[None] | None = None
        self._batches_processed = 0
        self._items_processed = 0
        # B12: Serialise start() calls so only one worker task is ever created.
        self._start_lock: asyncio.Lock | None = None

    @property
    def queue_depth(self) -> int:
        return self._queue.qsize() if self._queue is not None else 0

    @property
    def batch_fill_ratio(self) -> float:
        if self._batches_processed == 0:
            return 0.0
        return min(1.0, self._items_processed / (self._batches_processed * self.max_batch_size))

    def _get_start_lock(self) -> asyncio.Lock:
        """Return (and lazily create) the asyncio.Lock for start().

        asyncio.Lock must be created inside a running event loop, so we cannot
        create it in __init__ which may run before the loop is started.
        """
        if self._start_lock is None:
            self._start_lock = asyncio.Lock()
        return self._start_lock

    async def start(self) -> None:
        """Ensure the queue and worker task exist. Safe to call concurrently (B12)."""
        async with self._get_start_lock():
            if self._queue is None:
                self._queue = asyncio.Queue(maxsize=self.max_queue_size)
            if self._worker_task is None or self._worker_task.done():
                self._worker_task = asyncio.create_task(self._worker_loop())
                logger.debug("DynamicBatcher worker task (re)started")

    async def stop(self) -> None:
        if self._worker_task is not None:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None

    async def submit(self, texts: list[str], *, budget_ms: float | None = None) -> np.ndarray:
        if not texts:
            return np.zeros((0, 384), dtype=np.float32)

        # B12 fix: use the async start() so only one worker is ever created.
        if self._queue is None or self._worker_task is None or self._worker_task.done():
            await self.start()
        assert self._queue is not None

        if self._queue.qsize() >= self.max_queue_size:
            governor.record_429()
            raise HTTPException(
                status_code=429,
                detail={
                    "code": "queue_overloaded",
                    "message": "Hàng đợi xử lý AI đang đầy. Vui lòng thử lại sau ít giây.",
                },
                headers={"Retry-After": "2"},
            )

        loop = asyncio.get_running_loop()
        fut: asyncio.Future[np.ndarray] = loop.create_future()
        job = _BatchJob(texts=texts, future=fut)
        self._queue.put_nowait(job)

        timeout_s = (budget_ms / 1000.0) if (budget_ms is not None and budget_ms > 0) else 15.0
        try:
            return await asyncio.wait_for(fut, timeout=timeout_s)
        except asyncio.TimeoutError as exc:
            governor.record_504()
            raise HTTPException(
                status_code=504,
                detail={
                    "code": "budget_exceeded",
                    "message": "Yêu cầu vượt quá ngân sách thời gian xử lý cho phép.",
                },
            ) from exc

    async def _worker_loop(self) -> None:
        assert self._queue is not None
        while True:
            first_job = await self._queue.get()
            jobs = [first_job]
            total_texts = len(first_job.texts)
            deadline = time.perf_counter() + self.max_wait_s

            while total_texts < self.max_batch_size:
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    break
                try:
                    nxt = await asyncio.wait_for(self._queue.get(), timeout=remaining)
                    jobs.append(nxt)
                    total_texts += len(nxt.texts)
                except asyncio.TimeoutError:
                    break

            flat_texts: list[str] = []
            slices: list[tuple[int, int]] = []
            for j in jobs:
                start = len(flat_texts)
                flat_texts.extend(j.texts)
                slices.append((start, len(flat_texts)))

            try:
                all_vecs = await asyncio.to_thread(self._encode_fn, flat_texts)
                self._batches_processed += 1
                self._items_processed += len(flat_texts)
                for j, (s, e) in zip(jobs, slices):
                    if not j.future.done():
                        j.future.set_result(np.asarray(all_vecs[s:e], dtype=np.float32))
            except Exception as exc:
                logger.exception(
                    "Batch encode failed for %d texts across %d jobs", len(flat_texts), len(jobs)
                )
                for j in jobs:
                    if not j.future.done():
                        j.future.set_exception(exc)


class IdempotencyStore:
    def __init__(self, max_entries: int = 1024, ttl_seconds: float = 300.0) -> None:
        self._max = max(32, max_entries)
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._cache: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    def get(self, key: str | None) -> Any | None:
        if not key or not key.strip():
            return None
        norm = key.strip()[:128]
        now = time.monotonic()
        with self._lock:
            entry = self._cache.get(norm)
            if entry is None:
                return None
            exp, payload = entry
            if now >= exp:
                del self._cache[norm]
                return None
            self._cache.move_to_end(norm)
            return payload

    def set(self, key: str | None, payload: Any) -> None:
        if not key or not key.strip():
            return
        norm = key.strip()[:128]
        now = time.monotonic()
        with self._lock:
            self._cache[norm] = (now + self._ttl, payload)
            self._cache.move_to_end(norm)
            while len(self._cache) > self._max:
                self._cache.popitem(last=False)


def parse_budget_ms(request: Request) -> float | None:
    raw = request.headers.get("x-budget-ms") or request.query_params.get("budget_ms")
    if not raw:
        return None
    try:
        val = float(raw)
        if val <= 0:
            governor.record_504()
            raise HTTPException(
                status_code=504,
                detail={"code": "budget_exceeded", "message": "Ngân sách thời gian đã cạn (budget_ms <= 0)."},
            )
        return val
    except ValueError:
        return None


idempotency_store = IdempotencyStore()
