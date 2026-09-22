"""Pre-flight probe: retries for transient errors, fail-fast for 4xx,
and the --no-preflight escape hatch.

The bug these lock down: a single ConnectionResetError (server still loading
its weights, gateway hiccup) aborted the whole benchmark with a bare traceback
dump and no way to skip the probe.
"""

from __future__ import annotations

import asyncio

import pytest

import clawperf.runner as runner_mod
from clawperf.config import BenchmarkConfig
from clawperf.runner import BenchmarkRunner


class _FakeBody:
    def __init__(self, success=True, status_code=200, error=None):
        self.success = success
        self.status_code = status_code
        self.error = error


class _FakePlugin:
    def build_request(self, messages):
        return {"model": "m", "messages": messages}


class _FakeClient:
    """Returns/raises the queued outcomes in order; records every call."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    async def post(self, body):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class _FastAsyncio:
    """Proxy for the asyncio module with a no-op sleep (records the delays)."""

    def __init__(self, real):
        self._real = real
        self.sleeps: list = []

    def __getattr__(self, name):
        return getattr(self._real, name)

    async def sleep(self, delay):
        self.sleeps.append(delay)


def _runner(monkeypatch, outcomes, **cfg):
    config = BenchmarkConfig(endpoint="http://x/v1/chat/completions", model="m", **cfg)
    r = BenchmarkRunner(config)
    r._api_plugin = _FakePlugin()
    r._http_client = _FakeClient(outcomes)
    shim = _FastAsyncio(asyncio)
    monkeypatch.setattr(runner_mod, "asyncio", shim)
    return r, shim


async def test_no_preflight_skips_probe(monkeypatch):
    r, _ = _runner(monkeypatch, [], preflight=False)
    await r._preflight_check()
    assert r._http_client.calls == 0


async def test_success_first_try(monkeypatch):
    r, shim = _runner(monkeypatch, [_FakeBody()])
    await r._preflight_check()
    assert r._http_client.calls == 1
    assert shim.sleeps == []


async def test_transient_reset_is_retried_then_succeeds(monkeypatch):
    r, shim = _runner(monkeypatch, [
        ConnectionResetError(104, "Connection reset by peer"),
        ConnectionResetError(104, "Connection reset by peer"),
        _FakeBody(),
    ], preflight_retries=3)
    await r._preflight_check()
    assert r._http_client.calls == 3
    assert shim.sleeps == [1, 2]  # exponential backoff


async def test_persistent_reset_fails_with_hint(monkeypatch):
    r, _ = _runner(monkeypatch, [ConnectionResetError(104, "reset")] * 2,
                   preflight_retries=2)
    with pytest.raises(RuntimeError) as ei:
        await r._preflight_check()
    msg = str(ei.value)
    assert r._http_client.calls == 2
    assert "ConnectionResetError" in msg
    assert "--no-preflight" in msg


async def test_timeout_is_retried(monkeypatch):
    r, shim = _runner(monkeypatch, [asyncio.TimeoutError(), _FakeBody()],
                      preflight_retries=3)
    await r._preflight_check()
    assert r._http_client.calls == 2
    assert shim.sleeps == [1]


# EvalScope's AioHttpClient never raises: it returns BenchmarkData(success=False,
# status_code=None, error="<full traceback>"). This is exactly what the user saw.
_RESET_ERROR = """Traceback (most recent call last):
  File "/usr/local/lib/python3.12/site-packages/aiohttp/streams.py", line 705, in read
    await self._waiter
aiohttp.client_exceptions.ClientOSError: [Errno 104] Connection reset by peer
"""


async def test_transport_failure_with_no_status_is_retried(monkeypatch):
    r, shim = _runner(monkeypatch, [
        _FakeBody(False, None, _RESET_ERROR),
        _FakeBody(False, None, _RESET_ERROR),
        _FakeBody(),
    ], preflight_retries=3)
    await r._preflight_check()
    assert r._http_client.calls == 3
    assert shim.sleeps == [1, 2]


async def test_error_message_is_summarized_not_a_traceback_dump(monkeypatch):
    r, _ = _runner(monkeypatch, [_FakeBody(False, None, _RESET_ERROR)],
                   preflight_retries=1)
    with pytest.raises(RuntimeError) as ei:
        await r._preflight_check()
    msg = str(ei.value)
    assert "ClientOSError: [Errno 104] Connection reset by peer" in msg
    assert "File \"/usr/local" not in msg  # frames dropped
    assert "--no-preflight" in msg


def test_summarize_error_handles_empty_and_odd_input():
    from clawperf.runner import _summarize_error
    assert _summarize_error(None) == "no error detail"
    assert _summarize_error("") == "no error detail"
    assert _summarize_error("just a message") == "just a message"
    long = _summarize_error("E" * 500)
    assert len(long) < 300 and long.endswith("…")


async def test_4xx_is_not_retried(monkeypatch):
    r, shim = _runner(monkeypatch, [_FakeBody(False, 404, "model not found")],
                      preflight_retries=5)
    with pytest.raises(RuntimeError) as ei:
        await r._preflight_check()
    assert r._http_client.calls == 1  # wrong model: retrying cannot help
    assert shim.sleeps == []
    assert "404" in str(ei.value)


async def test_5xx_is_retried(monkeypatch):
    r, _ = _runner(monkeypatch, [_FakeBody(False, 503, "loading")] * 3,
                   preflight_retries=3)
    with pytest.raises(RuntimeError):
        await r._preflight_check()
    assert r._http_client.calls == 3


async def test_retries_floor_is_one(monkeypatch):
    r, _ = _runner(monkeypatch, [ConnectionResetError(104, "reset")],
                   preflight_retries=0)
    with pytest.raises(RuntimeError):
        await r._preflight_check()
    assert r._http_client.calls == 1


async def test_build_request_failure_is_clean(monkeypatch):
    r, _ = _runner(monkeypatch, [])

    def boom(messages):
        raise ValueError("no model")

    r._api_plugin.build_request = boom
    with pytest.raises(RuntimeError, match="failed to build request"):
        await r._preflight_check()


async def test_none_request_body_is_clean(monkeypatch):
    r, _ = _runner(monkeypatch, [])
    r._api_plugin.build_request = lambda messages: None
    with pytest.raises(RuntimeError, match="build_request returned None"):
        await r._preflight_check()
