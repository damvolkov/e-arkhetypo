"""tests/unit/e_infra/engines/health: every provider asked at once, each bounded, each verdict typed — never a raise."""

import asyncio
import time
from datetime import timedelta
from typing import TYPE_CHECKING, Final

import pytest

from e_infra.engines.health import HealthEngine, ProviderHealth
from unit.e_infra.engines.conftest import StubProvider

if TYPE_CHECKING:
    from unit.e_infra.conftest import Logs

LIMIT: Final[timedelta] = timedelta(seconds=1)
REQUIRED: Final[frozenset[str]] = frozenset({"store"})


async def test_survey_every_provider() -> None:
    """One verdict per provider, in mapping order, `required` read off the set."""
    engine = HealthEngine({"store": StubProvider(), "http": StubProvider()}, REQUIRED, LIMIT)
    assert [(h.name, h.required, h.ok, h.reason) for h in await engine.survey()] == [
        ("store", True, True, ""),
        ("http", False, True, ""),
    ]


async def test_survey_empty() -> None:
    assert await HealthEngine({}, REQUIRED, LIMIT).survey() == ()


async def test_survey_default_limit_is_the_ping_setting() -> None:
    assert HealthEngine({})._limit == timedelta(seconds=2)


async def test_survey_concurrent() -> None:
    """Three slow providers at once: the whole takes the slowest, not the sum."""
    slow = {name: StubProvider(delay=0.3) for name in ("store", "redis", "http")}
    start = time.perf_counter()
    verdicts = await HealthEngine(slow, REQUIRED, LIMIT).survey()
    elapsed = time.perf_counter() - start
    assert (all(v.ok for v in verdicts), elapsed < 0.6) == (True, True)
    assert min(v.latency for v in verdicts) >= 300


async def test_survey_timeout_isolated() -> None:
    """One provider that hangs is down past the limit, and holds none of the others."""
    start = time.perf_counter()
    named = {"store": StubProvider(), "http": StubProvider(delay=30)}
    verdicts = {v.name: v for v in await HealthEngine(named, REQUIRED, timedelta(seconds=0.2)).survey()}
    assert time.perf_counter() - start < 1
    assert (verdicts["http"].ok, verdicts["http"].reason) == (False, "no answer within 0.2s")
    assert verdicts["store"].ok


@pytest.mark.parametrize(
    ("provider", "reason", "latency"),
    [
        (StubProvider(up=False), "unhealthy", None),
        (StubProvider(error=ValueError("bad")), "ValueError: bad", None),
        (StubProvider(error=asyncio.CancelledError()), "CancelledError", 0.0),
    ],
    ids=["down", "breaks-contract", "cancelled"],
)
async def test_survey_failures(provider: StubProvider, reason: str, latency: float | None) -> None:
    """A provider down says why; a check cancelled under the gather is that provider's verdict, never the caller's."""
    (verdict,) = await HealthEngine({"store": provider}, REQUIRED, LIMIT).survey()
    assert verdict == ProviderHealth(
        name="store",
        required=True,
        ok=False,
        latency=verdict.latency if latency is None else latency,
        reason=reason,
    )


async def test_survey_logs_the_survey_and_warns_for_each_provider_that_is_down(logs: Logs) -> None:
    engine = HealthEngine({"store": StubProvider(up=False), "http": StubProvider()}, REQUIRED, LIMIT)
    await engine.survey()
    assert logs.at("debug") == ["health survey"]
    assert logs.at("warning") == ["provider down"]
    assert [fields["provider"] for level, _, fields in logs.events if level == "warning"] == ["store"]
