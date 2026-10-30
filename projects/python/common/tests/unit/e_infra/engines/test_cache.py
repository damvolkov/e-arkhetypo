"""tests/unit/e_infra/engines/cache: a fast layer in front of a durable one — read-through, write-both, degraded not failed."""

from typing import TYPE_CHECKING

import pytest

from e_infra.engines.cache import CacheEngine
from e_infra.infra.config.providers.adapters.cache.theine import TheineSettings
from e_infra.infra.errors import DatabaseError
from e_infra.providers.adapters.cache.theine import TheineAdapter
from unit.e_infra.conftest import Warnings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence


class Durable(TheineAdapter[int]):
    """A durable layer stand-in: the in-memory adapter, switchable to down, counting its reads."""

    def __init__(self) -> None:
        super().__init__(TheineSettings(size=100))
        self.down = False
        self.reads: list[Sequence[str]] = []

    async def many(self, keys: Sequence[str]) -> dict[str, int]:
        self.reads.append(keys)
        return await self._fail() or await super().many(keys)

    async def put_many(self, items: Mapping[str, int]) -> None:
        _ = await self._fail()
        await super().put_many(items)

    async def _fail(self) -> None:
        _ = self.down and self._raise()

    @staticmethod
    def _raise() -> None:
        msg = "durable layer down"
        raise DatabaseError(msg)


@pytest.fixture
async def layers() -> AsyncIterator[tuple[TheineAdapter[int], Durable]]:
    async with TheineAdapter[int](TheineSettings(size=100)) as fast, Durable() as durable:
        yield fast, durable


@pytest.fixture
def warnings(monkeypatch: pytest.MonkeyPatch) -> Warnings:
    recorder = Warnings()
    monkeypatch.setattr("e_infra.engines.cache.logger", recorder)
    return recorder


async def test_cache_write_goes_to_both_read_asks_fast_first(layers: tuple[TheineAdapter[int], Durable]) -> None:
    fast, durable = layers
    cache = CacheEngine(fast, durable, "ns")
    await cache.put_many({"a": 1, "b": 2})
    assert (await fast.get("a"), await durable.get("b")) == (1, 2)
    assert await cache.many(["a", "b"]) == {"a": 1, "b": 2}
    assert durable.reads == []


async def test_cache_a_durable_hit_is_kept_in_the_fast_layer(layers: tuple[TheineAdapter[int], Durable]) -> None:
    fast, durable = layers
    await durable.put("a", 1)
    cache = CacheEngine(fast, durable)
    assert (await cache.get("a"), await fast.get("a")) == (1, 1)
    assert await cache.get("missing") is None
    assert durable.reads == [["a"], ["missing"]]


async def test_cache_degrades_to_the_fast_layer_when_the_durable_is_down(
    layers: tuple[TheineAdapter[int], Durable], warnings: Warnings
) -> None:
    fast, durable = layers
    cache = CacheEngine(fast, durable, "ns")
    durable.down = True
    await cache.put("a", 1)
    assert (await cache.get("a"), await cache.get("b")) == (1, None)
    assert warnings.events == ["cache write degraded", "cache read degraded"]


async def test_cache_nothing_written_asks_no_one(layers: tuple[TheineAdapter[int], Durable]) -> None:
    fast, durable = layers
    cache = CacheEngine(fast, durable)
    await cache.put_many({})
    assert (await cache.many([]), durable.reads) == ({}, [])
