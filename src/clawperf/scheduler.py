"""User arrival scheduler — burst / steady / poisson — and request-rate pacing.

- Arrival schedulers yield (user_id, interval): the seconds to wait BEFORE
  launching each user (session arrival), relative to the previous launch.
- PoissonRateLimiter paces individual REQUESTS on a Poisson process
  (open-loop issue rate), matching vLLM benchmark_serving's --request-rate
  and evalscope's request-rate semantics.
"""

from __future__ import annotations

import asyncio
import random
import time
from typing import AsyncIterator


async def burst_scheduler(num_users: int) -> AsyncIterator[tuple[int, float]]:
    """All users start immediately — interval is 0 for every user."""
    for uid in range(num_users):
        yield uid, 0.0


async def steady_scheduler(num_users: int, interval: float) -> AsyncIterator[tuple[int, float]]:
    """Users arrive every *interval* seconds. First user at t=0."""
    for uid in range(num_users):
        yield uid, interval if uid > 0 else 0.0


async def poisson_scheduler(num_users: int, lambda_rate: float) -> AsyncIterator[tuple[int, float]]:
    """Users arrive following a Poisson process. Intervals ~ Exp(lambda_rate)."""
    for uid in range(num_users):
        yield uid, random.expovariate(lambda_rate) if uid > 0 else 0.0


def get_scheduler(config):
    if config.arrival_mode == "burst":
        return burst_scheduler(config.num_users)
    elif config.arrival_mode == "steady":
        return steady_scheduler(config.num_users, config.arrival_param)
    elif config.arrival_mode == "poisson":
        return poisson_scheduler(config.num_users, config.arrival_param)
    raise ValueError(f"Unknown arrival mode: {config.arrival_mode}")


class PoissonRateLimiter:
    """Open-loop request pacing: releases requests on a Poisson process.

    Inter-arrival gaps ~ Exp(rate) — i.e. a target of ``rate`` requests per
    second — the standard open-loop benchmark semantics (benchmark_serving
    ``--request-rate``). The first request is released immediately.

    Seeded RNG makes the schedule reproducible. If the caller falls behind
    (a slot is missed because the previous acquire slept too long), the next
    slot is computed from ``max(next_slot, now)`` so the schedule never
    bursts to catch up — an overloaded downstream is measured, not masked.

    Single-event-loop safe (asyncio.Lock around slot allocation).
    """

    def __init__(self, rate: float, seed: int = 0):
        if rate <= 0:
            raise ValueError(f"rate must be > 0 requests/second, got {rate}")
        self._rate = float(rate)
        self._rng = random.Random(seed)
        self._next_slot: float | None = None  # monotonic ts of the next free slot
        self._lock = asyncio.Lock()

    @property
    def rate(self) -> float:
        return self._rate

    def _next_gap(self) -> float:
        """Sample one inter-arrival gap (exposed for tests)."""
        return self._rng.expovariate(self._rate)

    async def acquire(self) -> float:
        """Wait for this request's slot.

        Returns the scheduled slot time (time.monotonic()); compare with
        time.monotonic() right after the call to measure release skew.
        """
        async with self._lock:
            now = time.monotonic()
            if self._next_slot is None:
                slot = now  # first request goes out immediately
            else:
                slot = max(self._next_slot, now) + self._next_gap()
            self._next_slot = slot
        delay = slot - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)
        return slot
