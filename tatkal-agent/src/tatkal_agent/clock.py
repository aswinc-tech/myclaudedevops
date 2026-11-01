"""Tatkal window maths and server-clock synchronisation.

Being "fast" at Tatkal is mostly about *when* the first request lands, not how
fast the code is. A laptop clock that is 2 s slow loses to everyone. We estimate
the offset to the booking server's clock (NTP-style, using RTT/2) and fire
exactly when the server's clock reads the opening time.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .models import AC_CLASSES

IST = ZoneInfo("Asia/Kolkata")


def tatkal_window_open(journey_date: date, travel_class: str) -> datetime:
    """Tatkal opens one day before the journey date (from the train's origin
    station): 10:00 IST for AC classes, 11:00 IST for non-AC classes."""
    day = journey_date - timedelta(days=1)
    hour = 10 if travel_class.upper() in AC_CLASSES else 11
    return datetime(day.year, day.month, day.day, hour, 0, 0, tzinfo=IST)


async def estimate_offset(
    server_time: Callable[[], Awaitable[datetime]], samples: int = 5
) -> tuple[float, float]:
    """Return (offset_seconds, best_rtt_seconds). offset = server - local.

    Uses the sample with the lowest round-trip time, which has the least
    queueing noise.
    """
    best: tuple[float, float] | None = None
    for _ in range(samples):
        t0 = time.time()
        server = await server_time()
        t1 = time.time()
        rtt = t1 - t0
        offset = server.timestamp() - (t0 + rtt / 2)
        if best is None or rtt < best[1]:
            best = (offset, rtt)
    assert best is not None
    return best


async def sleep_until(
    target: datetime,
    offset_seconds: float = 0.0,
    one_way_latency: float = 0.0,
    spin_window: float = 0.05,
) -> None:
    """Sleep until the *server* clock reaches `target`, then return.

    We aim to have the request arrive at the server at `target`, so we leave
    `one_way_latency` early. The last few ms are busy-waited because
    asyncio.sleep granularity is too coarse.
    """
    fire_at_local = target.timestamp() - offset_seconds - one_way_latency
    while True:
        remaining = fire_at_local - time.time()
        if remaining <= 0:
            return
        if remaining > spin_window:
            await asyncio.sleep(remaining - spin_window)
        else:
            await asyncio.sleep(0)
