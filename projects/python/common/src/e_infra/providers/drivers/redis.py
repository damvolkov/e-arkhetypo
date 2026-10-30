"""providers/drivers/redis: a store over redis.asyncio (the official client, async driver) — bytes in, bytes out."""

from contextlib import contextmanager
from typing import TYPE_CHECKING, ClassVar, Self, cast

import redis.asyncio as redis
from redis.exceptions import RedisError

from e_infra.infra.errors import ProviderError, StoreError
from e_infra.infra.settings import settings as st
from e_infra.ports.provider import Isolation, Locality, ProviderSpec, Workload

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Generator

    from e_infra.infra.config.redis import RedisSettings


##### TYPES #####
class RedisDriver:
    """Thin KV over a redis connection pool; bytes in, bytes out — decode stays off."""

    spec: ClassVar[ProviderSpec] = ProviderSpec(
        "redis", Locality.REMOTE, Workload.IO_BOUND, Isolation.LOOP, pooled=True
    )

    def __init__(self, settings: RedisSettings | None = None) -> None:
        ### the default is read on call, not at import: the settings singleton stays lazy.
        self._url = (st.redis if settings is None else settings).redis_url
        self._client: redis.Redis | None = None

    ##### PRIVATE METHODS #####

    @staticmethod
    @contextmanager
    def _common_guard() -> Generator[None]:
        """redis's own error, as the tree's `StoreError`."""
        try:
            yield
        except RedisError as error:
            raise StoreError(str(error)) from error

    def _common_open(self) -> redis.Redis:
        match self._client:
            case None:
                msg = "RedisDriver is not open: the lifespan opens it, handlers never do"
                raise StoreError(msg)
            case client:
                return client

    ############################################################

    ##### PUBLIC #####

    async def __aenter__(self) -> Self:
        self._client = redis.from_url(self._url)
        return self

    async def __aexit__(self, *exc: object) -> None:
        match self._client:
            case None:
                return
            case client:
                await client.aclose()
                self._client = None

    async def health(self) -> bool:
        """The protocol's own PING, on the pool: the first real round trip, since opening connects nothing."""
        try:
            with self._common_guard():
                await self._common_open().ping()
        except ProviderError:
            return False
        return True

    async def get(self, key: str) -> bytes | None:
        with self._common_guard():
            return cast("bytes | None", await self._common_open().get(key))

    async def set(self, key: str, value: bytes) -> None:
        with self._common_guard():
            await self._common_open().set(key, value)

    async def delete(self, key: str) -> None:
        with self._common_guard():
            await self._common_open().delete(key)

    async def keys(self, prefix: str = "") -> AsyncIterator[str]:
        """Keys starting with `prefix`, streamed with SCAN — never KEYS, never materialized, unordered."""
        with self._common_guard():
            async for key in self._common_open().scan_iter(match=f"{prefix}*"):
                yield cast("bytes", key).decode()
