"""Shared helpers of the online providers."""

from __future__ import annotations

import json
import time
import threading
from typing import Any, Callable, Mapping

from ..ports import Fetcher, ProviderError


class RateLimiter:
    """Blocks callers so that calls are at least ``interval_s`` apart."""

    def __init__(self, interval_s: float, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self._interval = interval_s
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        with self._lock:
            now = self._clock()
            delay = self._next - now
            if delay > 0:
                self._sleep(delay)
                now = self._next
            self._next = max(now, self._clock()) + self._interval


class JsonProvider:
    name = ""

    def __init__(self, fetcher: Fetcher, *, timeout_s: float = 4.0,
                 user_agent: str = "spotify-autoeq/0.1",
                 limiter: "RateLimiter | None" = None) -> None:
        self._fetcher = fetcher
        self._timeout = timeout_s
        self._headers: Mapping[str, str] = {"User-Agent": user_agent, "Accept": "application/json"}
        self._limiter = limiter

    def _get_json(self, url: str) -> Any:
        if self._limiter is not None:
            self._limiter.wait()
        body = self._fetcher(url, self._headers, self._timeout)
        try:
            return json.loads(body)
        except ValueError as exc:
            raise ProviderError(f"{self.name}: invalid JSON") from exc
