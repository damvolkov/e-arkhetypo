"""tests/unit/e_infra/providers/adapters/theine: values kept as they are, bounded by count, each for its time to live."""

from datetime import timedelta

import anyio
import pytest

from e_infra.infra.errors import ProviderError
from e_infra.ports.cache import CachePort
from e_infra.providers.adapters.theine import TheineAdapter


async def test_theine_roundtrip() -> None:
    async with TheineAdapter[dict[str, int]](size=10) as cache:
        assert isinstance(cache, CachePort)
        await cache.put("a", {"n": 1})
        await cache.put_many({"b": {"n": 2}, "c": {"n": 3}})
        assert await cache.get("a") is await cache.get("a")
        assert await cache.many(["a", "b", "z"]) == {"a": {"n": 1}, "b": {"n": 2}}
        assert (await cache.get("z"), await cache.many([])) == (None, {})


async def test_theine_ttl() -> None:
    async with TheineAdapter[int](size=10, ttl=timedelta(milliseconds=50)) as cache:
        await cache.put("a", 1)
        assert await cache.get("a") == 1
        await anyio.sleep(0.15)
        assert await cache.get("a") is None


async def test_theine_lifecycle() -> None:
    cache = TheineAdapter[int](size=10)
    assert not await cache.health()
    with pytest.raises(ProviderError, match="not open"):
        await cache.get("a")
    async with cache:
        assert await cache.health()
        await cache.put("a", 1)
    assert not await cache.health()
    async with cache:
        assert await cache.get("a") is None
