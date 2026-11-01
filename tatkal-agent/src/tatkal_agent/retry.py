"""Deadline-aware retry with decorrelated jitter.

Tatkal is a thundering-herd problem: lakhs of clients hit the same endpoint at
10:00:00. Fixed-interval retries synchronise with everyone else and make it
worse; decorrelated jitter spreads load while still retrying aggressively
inside a hard overall deadline.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TypeVar

from .errors import NotWindowOpenError, RateLimitedError, TransientError

T = TypeVar("T")


@dataclass
class RetryPolicy:
    base_delay: float = 0.15
    max_delay: float = 1.0
    max_attempts: int = 25
    deadline_seconds: float = 120.0
    retry_on: tuple[type[BaseException], ...] = (TransientError, NotWindowOpenError)
    rng: random.Random = field(default_factory=random.Random)

    def next_delay(self, previous: float) -> float:
        # "Decorrelated jitter" (AWS Architecture Blog): sleep = min(cap, rand(base, prev*3))
        return min(self.max_delay, self.rng.uniform(self.base_delay, max(self.base_delay, previous * 3)))


async def retry_async(
    fn: Callable[[], Awaitable[T]],
    policy: RetryPolicy,
    on_retry: Callable[[int, BaseException, float], None] | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> T:
    start = time.monotonic()
    delay = policy.base_delay
    attempt = 0
    while True:
        attempt += 1
        try:
            return await fn()
        except policy.retry_on as exc:  # type: ignore[misc]
            elapsed = time.monotonic() - start
            if attempt >= policy.max_attempts or elapsed >= policy.deadline_seconds:
                raise
            if isinstance(exc, RateLimitedError):
                delay = max(exc.retry_after, policy.base_delay)
            else:
                delay = policy.next_delay(delay)
            delay = min(delay, max(0.0, policy.deadline_seconds - elapsed))
            if on_retry:
                on_retry(attempt, exc, delay)
            await sleep(delay)
