"""engines/cache: a fast cache in front of a durable one — the cache every module takes.

A read asks the fast layer first, then the durable one for what the fast one lacked, and keeps what it found in the fast
one. A write goes to both. The durable layer failing is a degraded cache, never a failed caller: the miss or the write
is logged and the cache goes on in the fast layer alone, for that call. Which providers are the layers — theine over
Postgres, any pair of `CachePort`s — is the composition root's decision; a module names its namespace and never meets a
backend."""

from typing import TYPE_CHECKING

from e_infra.infra.errors import ProviderError
from e_infra.infra.logger import logger

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from e_infra.ports.cache import CachePort


class CacheEngine[T]:
    """A fast cache in front of a durable one, with the `CachePort` operations."""

    __slots__ = ("_durable", "_fast", "_namespace")

    def __init__(self, fast: CachePort[T], durable: CachePort[T], namespace: str = "") -> None:
        self._fast = fast
        self._durable = durable
        self._namespace = namespace

    ##### PRIVATE #####

    async def _many_durable(self, keys: Sequence[str]) -> dict[str, T]:
        try:
            return await self._durable.many(keys)
        except ProviderError as error:
            logger.warning("cache read degraded", namespace=self._namespace, error=str(error), step="CACHE")
            return {}

    async def _put_durable(self, items: Mapping[str, T]) -> None:
        try:
            await self._durable.put_many(items)
        except ProviderError as error:
            logger.warning("cache write degraded", namespace=self._namespace, error=str(error), step="CACHE")

    ############################################################

    ##### PUBLIC #####

    async def get(self, key: str) -> T | None:
        return (await self.many([key])).get(key)

    async def many(self, keys: Sequence[str]) -> dict[str, T]:
        fast = await self._fast.many(keys)
        missed = [key for key in keys if key not in fast]
        durable = await self._many_durable(missed) if missed else {}
        _ = durable and await self._fast.put_many(durable)
        return {**fast, **durable}

    async def put(self, key: str, value: T) -> None:
        await self.put_many({key: value})

    async def put_many(self, items: Mapping[str, T]) -> None:
        await self._fast.put_many(items)
        _ = items and await self._put_durable(items)
