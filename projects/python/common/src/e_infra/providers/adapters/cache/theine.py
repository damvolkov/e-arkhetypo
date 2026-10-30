"""providers/adapters/cache/theine: a cache in this process's memory — theine (Rust core, W-TinyLFU, per-key TTL).

Bounded by count: past `size` entries the least likely to be read again is evicted. Values are kept as they are, never
serialized: the fast layer in front of a durable one, and the whole cache when no durable one answers."""

from typing import TYPE_CHECKING, ClassVar, Self

from theine import Cache

from e_infra.infra.errors import CacheError
from e_infra.infra.logger import logger
from e_infra.infra.settings import settings as st
from e_infra.ports.provider import Isolation, Locality, ProviderSpec, Workload

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from e_infra.infra.config.providers.adapters.cache.theine import TheineSettings


##### ADAPTER #####
class TheineAdapter[T]:
    """Values of type T in memory, at most CACHE_SIZE, each kept CACHE_TTL."""

    spec: ClassVar[ProviderSpec] = ProviderSpec("theine", Locality.EMBEDDED, Workload.CPU_BOUND, Isolation.LOOP)

    __slots__ = ("_conf", "_store")

    def __init__(self, settings: TheineSettings | None = None) -> None:
        ### the default is read on call, not at import: the settings singleton stays lazy.
        self._conf = st.providers.adapters.cache.theine if settings is None else settings
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
        self._store = Cache(self._conf.size)
        logger.info("theine opened", size=self._conf.size, ttl=str(self._conf.ttl))
        return self

    async def __aexit__(self, *exc: object) -> None:
        self._store = None
        logger.info("theine closed")

    async def health(self) -> bool:
        opened = self._store is not None
        _ = opened or logger.warning("theine unhealthy", reason="not open")
        return opened

    async def get(self, key: str) -> T | None:
        value, found = self._common_open().get(key)
        logger.debug("theine get", key=key, hit=found)
        return value if found else None

    async def many(self, keys: Sequence[str]) -> dict[str, T]:
        store = self._common_open()
        found = ((key, store.get(key)) for key in keys)
        hits = {key: value for key, (value, hit) in found if hit and value is not None}
        logger.debug("theine many", keys=len(keys), hits=len(hits))
        return hits

    async def put(self, key: str, value: T) -> None:
        logger.debug("theine put", key=key)
        self._common_open().set(key, value, self._conf.ttl)

    async def put_many(self, items: Mapping[str, T]) -> None:
        store = self._common_open()
        logger.debug("theine put many", keys=len(items))
        _ = [store.set(key, value, self._conf.ttl) for key, value in items.items()]
