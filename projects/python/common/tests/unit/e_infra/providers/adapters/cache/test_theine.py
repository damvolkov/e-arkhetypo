"""e_infra/providers/adapters/cache/theine: values kept as they are, bounded by count, each for its time to live."""

from datetime import timedelta
from typing import TYPE_CHECKING

import anyio
import pytest

from e_infra.infra.errors import CacheError, ProviderError
from e_infra.ports.cache import CachePort
from e_infra.providers.adapters.cache.theine import TheineAdapter
from unit.e_infra.conftest import theine_args

if TYPE_CHECKING:
    from unit.e_infra.conftest import Logs


async def test_theine_roundtrip() -> None:
    async with TheineAdapter[dict[str, int]](**theine_args(size=10)) as cache:
        assert isinstance(cache, CachePort)
        await cache.put("a", {"n": 1})
        await cache.put_many({"b": {"n": 2}, "c": {"n": 3}})
        assert await cache.get("a") is await cache.get("a")
        assert await cache.many(["a", "b", "z"]) == {"a": {"n": 1}, "b": {"n": 2}}
        assert (await cache.get("z"), await cache.many([])) == (None, {})


async def test_theine_ttl() -> None:
    async with TheineAdapter[int](**theine_args(size=10, ttl=timedelta(milliseconds=50))) as cache:
        await cache.put("a", 1)
        assert await cache.get("a") == 1
        await anyio.sleep(0.15)
        assert await cache.get("a") is None


async def test_theine_without_a_ttl_keeps_until_evicted() -> None:
    async with TheineAdapter[int](**theine_args(size=10, ttl=None)) as cache:
        await cache.put("a", 1)
        await anyio.sleep(0.1)
        assert await cache.get("a") == 1


async def test_theine_lifecycle() -> None:
    cache = TheineAdapter[int](**theine_args(size=10))
    with pytest.raises(ProviderError):
        await cache.health()
    with pytest.raises(CacheError, match="not open"):
        await cache.get("a")
    async with cache:
        assert await cache.health()
        await cache.put("a", 1)
    with pytest.raises(ProviderError):
        await cache.health()
    async with cache:
        assert await cache.get("a") is None


async def test_theine_lifecycle_and_an_unopened_health_are_logged(logs: Logs) -> None:
    cache = TheineAdapter[int](**theine_args(size=10, ttl=timedelta(minutes=1)))
    with pytest.raises(ProviderError):
        await cache.health()
    async with cache:
        await cache.put("a", 1)
        await cache.put_many({"b": 2})
        assert (await cache.get("a"), await cache.get("z"), await cache.many(["a", "b"])) == (1, None, {"a": 1, "b": 2})
    assert logs.at("info") == ["theine opened", "theine closed"]
    assert logs.at("warning") == ["theine unhealthy"]
    assert logs.at("debug") == ["theine put", "theine put many", "theine get", "theine get", "theine many"]
