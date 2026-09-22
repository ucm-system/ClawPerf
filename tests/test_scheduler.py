"""Tests for user arrival schedulers — verify intervals, not absolute times."""

from __future__ import annotations

import asyncio
import time as _time

import pytest

from clawperf.config import BenchmarkConfig
from clawperf.scheduler import (
    PoissonRateLimiter,
    burst_scheduler,
    get_scheduler,
    poisson_scheduler,
    steady_scheduler,
)


@pytest.mark.asyncio
async def test_burst_scheduler():
    """Burst: all intervals are 0 (users start simultaneously)."""
    results = []
    async for uid, interval in burst_scheduler(5):
        results.append((uid, interval))
    assert len(results) == 5
    assert all(d == 0.0 for _, d in results)
    assert [uid for uid, _ in results] == [0, 1, 2, 3, 4]


@pytest.mark.asyncio
async def test_steady_scheduler():
    """Steady: first user interval=0, rest interval=param."""
    results = []
    async for uid, interval in steady_scheduler(4, interval=2.0):
        results.append((uid, interval))
    assert len(results) == 4
    assert results[0] == (0, 0.0)   # first user starts immediately
    assert results[1] == (1, 2.0)   # wait 2s before user 1
    assert results[2] == (2, 2.0)   # wait 2s before user 2
    assert results[3] == (3, 2.0)   # wait 2s before user 3
    # Total arrival timeline: 0s, 2s, 4s, 6s (cumulative)


@pytest.mark.asyncio
async def test_poisson_scheduler_intervals():
    """Poisson: first interval=0, rest are exponential intervals."""
    results = []
    async for uid, interval in poisson_scheduler(10, lambda_rate=1.0):
        results.append((uid, interval))
    assert len(results) == 10
    assert results[0] == (0, 0.0)   # first user starts immediately
    # All other intervals should be positive (not cumulative)
    for uid, interval in results[1:]:
        assert interval > 0


def test_get_scheduler_burst():
    cfg = BenchmarkConfig(endpoint="http://x", model="m", num_users=3, user_arrival="burst")
    scheduler = get_scheduler(cfg)
    assert scheduler is not None


def test_get_scheduler_steady():
    cfg = BenchmarkConfig(endpoint="http://x", model="m", num_users=3, user_arrival="steady:1")
    scheduler = get_scheduler(cfg)
    assert scheduler is not None


def test_get_scheduler_invalid():
    cfg = BenchmarkConfig(endpoint="http://x", model="m", user_arrival="burst")
    cfg.arrival_mode = "unknown"
    with pytest.raises(ValueError, match="Unknown arrival mode"):
        get_scheduler(cfg)

# ── PoissonRateLimiter (open-loop request pacing) ─────────────────────────────


def test_rate_limiter_rejects_bad_rate():
    for bad in (0, -1):
        with pytest.raises(ValueError):
            PoissonRateLimiter(bad)


def test_rate_limiter_gap_determinism():
    """Same seed → same sampled gap sequence (reproducible schedules)."""
    a = PoissonRateLimiter(2.0, seed=42)
    b = PoissonRateLimiter(2.0, seed=42)
    ga = [a._next_gap() for _ in range(20)]
    gb = [b._next_gap() for _ in range(20)]
    assert ga == gb
    assert all(g > 0 for g in ga)
    # Mean of Exp(rate) is 1/rate; with 200 samples it should be in the right
    # ballpark (loose bounds to avoid flakiness).
    many = [a._next_gap() for _ in range(200)]
    assert 0.5 / 2.0 < sum(many) / len(many) < 2.0 / 2.0


@pytest.mark.asyncio
async def test_rate_limiter_first_immediate_rest_paced():
    """First acquire returns immediately; subsequent slots are spaced by the
    sampled gaps (measured via the returned slot times)."""
    lim = PoissonRateLimiter(50.0, seed=7)  # high rate → fast test
    t0 = _time.monotonic()
    slot1 = await lim.acquire()
    assert slot1 - t0 < 0.05  # first request goes out immediately
    slot2 = await lim.acquire()
    assert slot2 > slot1  # slots strictly increase
    slot3 = await lim.acquire()
    assert slot3 > slot2
    # Total elapsed roughly matches the two sampled gaps (loose bound).
    elapsed = _time.monotonic() - t0
    assert elapsed < 2.0


@pytest.mark.asyncio
async def test_rate_limiter_no_catch_up_burst():
    """A missed slot must not cause a burst: after a delay, the next slot is
    computed from now (max(next_slot, now)), never in the past."""
    lim = PoissonRateLimiter(100.0, seed=3)
    await lim.acquire()
    await asyncio.sleep(0.1)  # fall behind
    before = _time.monotonic()
    slot = await lim.acquire()
    # The slot must not be scheduled in the past, and not more than one mean
    # gap (0.01s) plus slack into the future.
    assert slot >= before - 0.001
    assert slot <= before + 0.5


@pytest.mark.asyncio
async def test_rate_limiter_concurrent_acquires():
    """Many concurrent acquires serialize cleanly on one shared schedule."""
    lim = PoissonRateLimiter(200.0, seed=11)
    slots = await asyncio.gather(*[lim.acquire() for _ in range(10)])
    assert len(set(slots)) == 10  # every request got a distinct slot
    assert list(slots) == sorted(slots)  # allocation order == slot order


def test_config_rejects_negative_request_rate():
    from clawperf.config import BenchmarkConfig

    cfg = BenchmarkConfig(endpoint="http://x", model="m", mode="hitrate", request_rate=-2)
    problems = cfg.validate()
    assert any("request_rate" in p for p in problems)
    ok = BenchmarkConfig(endpoint="http://x", model="m", mode="hitrate", request_rate=2.5)
    assert not any("request_rate" in p for p in ok.validate())


@pytest.mark.asyncio
async def test_replay_player_open_loop_pacing(monkeypatch):
    """Open-loop replay: requests carry rate_skew_ms and pacing actually delays."""
    from clawperf.player import ReplayPlayer, ReplayResult

    sent = []

    async def fake_send(self, req):
        sent.append(_time.monotonic())
        return ReplayResult(index=req.index, success=True, e2e_ms=1.0)

    monkeypatch.setattr(ReplayPlayer, "_send_request", fake_send)
    entries = [{"index": i, "messages": [{"role": "user", "content": "hi"}]}
               for i in range(5)]
    p = ReplayPlayer(endpoint="http://x", model="m",
                     request_rate=100.0, rate_seed=5, concurrency=1)
    results = await p.replay(entries)
    assert len(results) == 5
    assert all(r.success for r in results)
    # Open-loop path must record release skew on every result.
    assert all(r.rate_skew_ms is not None for r in results)
    # 4 Exp(100) gaps ≈ 40ms total — requests were actually spaced (and the
    # concurrency=1 semaphore did NOT serialize them to 5 sequential sends).
    assert sent[-1] - sent[0] < 1.0
    assert sent == sorted(sent)


@pytest.mark.asyncio
async def test_replay_player_closed_loop_no_skew(monkeypatch):
    """Closed-loop (rate=0): no limiter, no skew fields — old behavior."""
    from clawperf.player import ReplayPlayer, ReplayResult

    async def fake_send(self, req):
        return ReplayResult(index=req.index, success=True, e2e_ms=1.0)

    monkeypatch.setattr(ReplayPlayer, "_send_request", fake_send)
    entries = [{"index": i, "messages": [{"role": "user", "content": "hi"}]}
               for i in range(3)]
    p = ReplayPlayer(endpoint="http://x", model="m")
    results = await p.replay(entries)
    assert all(r.rate_skew_ms is None for r in results)
