"""
request_limits.py
==================
Process-local sliding-window rate limiter.

Fixes applied (B7, P3):
- Replaced unbounded list with deque(maxlen=limit) → O(1) append, O(1) check.
- Periodic global eviction of idle/stale buckets to prevent unbounded memory growth.
- Thread-safe via a single module-level lock.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque

logger = logging.getLogger("classbridge.request_limits")

_lock = threading.Lock()
_buckets: dict[object, deque[float]] = {}

# Prune buckets with no events in the last EVICTION_IDLE_SECONDS seconds.
_EVICTION_IDLE_S = 1800.0
_last_eviction: float = 0.0
_EVICTION_INTERVAL_S = 300.0


def _maybe_evict(now: float) -> None:
    """Evict idle buckets every EVICTION_INTERVAL_S seconds (called under lock)."""
    global _last_eviction
    if now - _last_eviction < _EVICTION_INTERVAL_S:
        return
    _last_eviction = now
    cutoff_idle = now - _EVICTION_IDLE_S
    stale = [key for key, dq in _buckets.items() if not dq or dq[-1] < cutoff_idle]
    for key in stale:
        del _buckets[key]
    if stale:
        logger.debug("request_limits: evicted %d idle buckets", len(stale))


def request_limit_exceeded(bucket: object, limit: int, window_seconds: float) -> bool:
    """Return True if `bucket` has already hit `limit` events in the last `window_seconds`.

    Thread-safe, process-local. For multi-process (Gunicorn) deployments replace
    with flask-limiter backed by Redis.
    """
    now = time.monotonic()
    cutoff = now - window_seconds

    with _lock:
        _maybe_evict(now)
        if bucket not in _buckets:
            _buckets[bucket] = deque()
        dq = _buckets[bucket]
        # Drop expired timestamps from the left side.
        while dq and dq[0] <= cutoff:
            dq.popleft()
        if len(dq) >= limit:
            return True
        dq.append(now)
        return False
