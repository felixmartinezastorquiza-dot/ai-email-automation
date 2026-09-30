"""In-memory abuse protection for the public demo: per-IP rate limits and a global daily quota.

In-memory state is fine for a single server instance. With several instances, this state
would move to a shared store such as Redis.
"""

import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from datetime import UTC, datetime

from starlette.requests import Request

MAX_TRACKED_KEYS = 10_000


class SlidingWindowRateLimiter:
    """Allow at most `max_requests` per key within any `window_seconds` period."""

    def __init__(
        self,
        max_requests: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_requests = max_requests
        self._window = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> float | None:
        """Record a request. Return None if allowed, or the seconds to wait if limited."""
        now = self._clock()
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= now - self._window:
                hits.popleft()
            if len(hits) >= self._max_requests:
                return self._window - (now - hits[0])
            hits.append(now)
            if len(self._hits) > MAX_TRACKED_KEYS:
                self._forget_idle_keys(now)
            return None

    def _forget_idle_keys(self, now: float) -> None:
        idle = [k for k, hits in self._hits.items() if not hits or hits[-1] <= now - self._window]
        for key in idle:
            del self._hits[key]

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


class DailyQuota:
    """Global cap on requests per UTC day: a hard ceiling on API spend."""

    def __init__(
        self,
        max_per_day: int,
        today: Callable[[], str] = lambda: datetime.now(UTC).date().isoformat(),
    ) -> None:
        self._max_per_day = max_per_day
        self._today = today
        self._day = ""
        self._count = 0
        self._lock = threading.Lock()

    def consume(self) -> bool:
        """Count one request. Return False if today's quota is already used up."""
        with self._lock:
            day = self._today()
            if day != self._day:
                self._day, self._count = day, 0
            if self._count >= self._max_per_day:
                return False
            self._count += 1
            return True

    def reset(self) -> None:
        with self._lock:
            self._day, self._count = "", 0


def client_ip(request: Request, trusted_proxy_hops: int) -> str:
    """Best-effort client IP.

    Behind N trusted proxies, the real client is the N-th address from the right of
    X-Forwarded-For (entries further left can be forged by the client). With no proxy,
    use the socket address.
    """
    if trusted_proxy_hops > 0:
        forwarded = [ip.strip() for ip in request.headers.get("x-forwarded-for", "").split(",")]
        forwarded = [ip for ip in forwarded if ip]
        if len(forwarded) >= trusted_proxy_hops:
            return forwarded[-trusted_proxy_hops]
    return request.client.host if request.client else "unknown"
