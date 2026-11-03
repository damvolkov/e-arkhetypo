"""tests/unit/e_infra/ops/wrappers: latency is live inside the block, frozen after, and survives a raise."""

import asyncio

import pytest

from e_infra.ops.wrappers import LatencyWrapper


async def test_latency_measures_an_awaited_block() -> None:
    with LatencyWrapper() as latency:
        await asyncio.sleep(0.01)
    assert latency.ms >= 10


def test_latency_live_inside_frozen_after() -> None:
    with LatencyWrapper() as latency:
        first = latency.ms
        second = latency.ms
    frozen = latency.ms
    assert 0 <= first <= second <= frozen
    assert latency.ms == frozen


def test_latency_frozen_when_the_block_raises() -> None:
    latency, msg = LatencyWrapper(), "boom"
    with pytest.raises(ValueError, match=msg), latency:
        raise ValueError(msg)
    assert latency.ms == latency.ms > 0


def test_latency_reentry_restarts_the_clock() -> None:
    latency = LatencyWrapper()
    with latency:
        pass
    with latency:
        assert latency.ms >= 0
