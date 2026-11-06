"""tests/support/cache: the caches a test stands in for — a `PostgresCacheDriver` over a database port, one in memory.

`cache` builds the durable driver, its time to live the only argument a test varies. `MemoryCache` is a `CachePort`
holding a dict, yielding on each read, counting what it was asked, and failing every call as a `CacheError` while `down`;
`model_cache` the engine's two caches in memory, under a mode (OFF by default: a test that is not about the cache never
meets it)."""

from typing import TYPE_CHECKING, Any, ClassVar, Self

import anyio.lowlevel

from e_infra.engines.llm import ModelCache
from e_infra.infra.config.engines import CacheMode
from e_infra.infra.errors import CacheError
from e_infra.ports.provider import Isolation, Locality, ProviderSpec, Workload
from e_infra.providers.drivers.cache.postgres import PostgresCacheDriver

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import timedelta

    from e_infra.ports.database import DatabasePort


def cache(
    db: DatabasePort, kind: type = int, namespace: str = "unit", *, ttl: timedelta | None = None
) -> PostgresCacheDriver:
    return PostgresCacheDriver(db, namespace, kind, ttl=ttl)


class MemoryCache[T]:
    """A `CachePort` in a dict: `reads` counts the keys asked, `writes` the values kept; `down` fails every call."""

    spec: ClassVar[ProviderSpec] = ProviderSpec("cache-memory", Locality.EMBEDDED, Workload.IO_BOUND, Isolation.LOOP)

    def __init__(self) -> None:
        self.held: dict[str, T] = {}
        self.reads = self.writes = 0
        self.down = False

    def _check(self) -> None:
        match self.down:
            case True:
                msg = "cache down"
                raise CacheError(msg)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Nothing to release."""

    async def health(self) -> bool:
        return not self.down

    async def get(self, key: str) -> T | None:
        return (await self.many([key])).get(key)

    async def many(self, keys: Sequence[str]) -> dict[str, T]:
        """What was held when asked, answered after a yield, as over the wire: two readers at once both miss."""
        self._check()
        self.reads += len(keys)
        found = {key: self.held[key] for key in keys if key in self.held}
        await anyio.lowlevel.checkpoint()
        return found

    async def put(self, key: str, value: T) -> None:
        await self.put_many({key: value})

    async def put_many(self, items: Mapping[str, T]) -> None:
        self._check()
        self.writes += len(items)
        self.held |= items


def model_cache(mode: CacheMode = CacheMode.OFF) -> ModelCache:
    return ModelCache(MemoryCache[Any](), MemoryCache[list[float]](), mode)
