"""tests/unit/e_infra/adapters/base: every adapter pinged at once, each bounded, each verdict typed — never a raise."""

import asyncio
import time
from datetime import timedelta
from typing import Final

import pytest

from e_infra.adapters.base import AdapterPing, BaseAdapter, PingError
from e_infra.adapters.conftest import StubAdapter

LIMIT: Final[timedelta] = timedelta(seconds=1)
REQUIRED: Final[frozenset[str]] = frozenset({"store"})


async def test_survey_every_adapter() -> None:
    """One verdict per adapter, in mapping order, `required` read off the set."""
    pings = await BaseAdapter.survey({"store": StubAdapter(), "http": StubAdapter()}, LIMIT, REQUIRED)
    assert [(ping.name, ping.required, ping.ok, ping.reason) for ping in pings] == [
        ("store", True, True, ""),
        ("http", False, True, ""),
    ]


async def test_survey_empty() -> None:
    assert await BaseAdapter.survey({}, LIMIT, REQUIRED) == ()


async def test_survey_concurrent() -> None:
    """Three slow providers at once: the whole takes the slowest, not the sum."""
    slow = {name: StubAdapter(delay=0.3) for name in ("store", "redis", "http")}
    start = time.perf_counter()
    pings = await BaseAdapter.survey(slow, LIMIT, REQUIRED)
    elapsed = time.perf_counter() - start
    assert (all(ping.ok for ping in pings), elapsed < 0.6) == (True, True)
    assert min(ping.latency for ping in pings) >= 300


async def test_survey_timeout_isolated() -> None:
    """One provider that hangs is down past the limit, and holds none of the others."""
    start = time.perf_counter()
    named = {"store": StubAdapter(), "http": StubAdapter(delay=30)}
    pings = {ping.name: ping for ping in await BaseAdapter.survey(named, timedelta(seconds=0.2), REQUIRED)}
    assert time.perf_counter() - start < 1
    assert (pings["http"].ok, pings["http"].reason) == (False, "no answer within 0.2s")
    assert pings["store"].ok


@pytest.mark.parametrize(
    ("down", "reason", "latency"),
    [
        (PingError("redis", "connection refused"), "redis: connection refused", None),
        (ValueError("bad"), "bad", None),
        (asyncio.CancelledError(), "CancelledError", 0.0),
    ],
    ids=["ping-error", "any-error", "cancelled"],
)
async def test_survey_failures(down: BaseException, reason: str, latency: float | None) -> None:
    """A provider down says why; a ping cancelled under the gather is that adapter's verdict, never the caller's."""
    (ping,) = await BaseAdapter.survey({"store": StubAdapter(down=down)}, LIMIT, REQUIRED)
    assert ping == AdapterPing(
        name="store", required=True, ok=False, latency=ping.latency if latency is None else latency, reason=reason
    )
