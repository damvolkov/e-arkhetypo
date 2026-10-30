"""providers/adapters/cache/theine: a cache in this process's memory — theine (Rust core, W-TinyLFU admission, per-key TTL).

Bounded by count: past `size` entries the least likely to be read again is evicted. Values are kept as they are, never
serialized: the fast layer in front of a durable one, and the whole cache when no durable one answers."""

from typing import TYPE_CHECKING, ClassVar, Self

from theine import Cache

from e_infra.infra.errors import CacheError
from e_infra.ports.provider import Isolation, Locality, ProviderSpec, Workload

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import timedelta


##### ADAPTER #####
class TheineAdapter[T]:
    """Values of type T in memory, at most `size`, each kept `ttl` (None: until evicted)."""

    spec: ClassVar[ProviderSpec] = ProviderSpec("theine", Locality.EMBEDDED, Workload.CPU_BOUND, Isolation.LOOP)

    __slots__ = ("_size", "_store", "_ttl")

    def __init__(self, size: int, ttl: timedelta | None = None) -> None:
        self._size = size
        self._ttl = ttl
        self._store: Cache[str, T] | None = None

    ##### PRIVATE #####

    def _common_open(self) -> Cache[str, T]:
        match self._store:
            case None:
                msg = "TheineAdapter is not open: the lifespan opens it, callers never do"
                raise CacheError(msg)
            case store:
                return store

    ############################################################

    ##### PUBLIC #####

    async def __aenter__(self) -> Self:
        self._store = Cache(self._size)
        return self

    async def __aexit__(self, *exc: object) -> None:
        self._store = None

    async def health(self) -> bool:
        return self._store is not None

    async def get(self, key: str) -> T | None:
        value, found = self._common_open().get(key)
        return value if found else None

    async def many(self, keys: Sequence[str]) -> dict[str, T]:
        store = self._common_open()
        found = ((key, store.get(key)) for key in keys)
        return {key: value for key, (value, hit) in found if hit and value is not None}

    async def put(self, key: str, value: T) -> None:
        self._common_open().set(key, value, self._ttl)

    async def put_many(self, items: Mapping[str, T]) -> None:
        store = self._common_open()
        _ = [store.set(key, value, self._ttl) for key, value in items.items()]
