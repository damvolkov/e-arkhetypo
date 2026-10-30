"""providers/drivers/store/redis: a store over redis.asyncio (the official client, async driver) — bytes in, bytes out."""

from contextlib import contextmanager
from typing import TYPE_CHECKING, ClassVar, Self, cast

import redis.asyncio as redis
from redis.exceptions import RedisError

from e_infra.infra.errors import ProviderError, StoreError
from e_infra.infra.logger import logger
from e_infra.infra.settings import settings as st
from e_infra.ports.provider import Isolation, Locality, ProviderSpec, Workload

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Generator

    from e_infra.infra.config.providers.drivers.store.redis import RedisSettings


##### TYPES #####
class RedisDriver:
    """Thin KV over a redis connection pool; bytes in, bytes out — decode stays off."""

    spec: ClassVar[ProviderSpec] = ProviderSpec(
        "redis", Locality.REMOTE, Workload.IO_BOUND, Isolation.LOOP, pooled=True
    )

    def __init__(self, settings: RedisSettings | None = None) -> None:
        ### the default is read on call, not at import: the settings singleton stays lazy.
        self._conf = st.providers.drivers.store.redis if settings is None else settings
        self._client: redis.Redis | None = None

    ##### PRIVATE METHODS #####

    @staticmethod
    @contextmanager
    def _common_guard() -> Generator[None]:
        """redis's own error, as the tree's `StoreError`."""
        try:
            yield
        except RedisError as error:
            logger.error("redis failed", error=str(error))
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
        timeout = self._conf.timeout.total_seconds()
        self._client = redis.from_url(
            self._conf.url.get_secret_value(),
            max_connections=self._conf.pool,
            socket_timeout=timeout,
            socket_connect_timeout=timeout,
        )
        logger.info("redis opened", pool=self._conf.pool)
        return self

    async def __aexit__(self, *exc: object) -> None:
        match self._client:
            case None:
                return
            case client:
                await client.aclose()
                self._client = None
                logger.info("redis closed")

    async def health(self) -> bool:
        """The protocol's own PING, on the pool: the first real round trip, since opening connects nothing."""
        try:
            with self._common_guard():
                await self._common_open().ping()
        except ProviderError as error:
            logger.warning("redis unhealthy", error=str(error))
            return False
        return True

    async def get(self, key: str) -> bytes | None:
        logger.debug("redis get", key=key)
        with self._common_guard():
            return cast("bytes | None", await self._common_open().get(key))

    async def set(self, key: str, value: bytes) -> None:
        logger.debug("redis set", key=key, size=len(value))
        with self._common_guard():
            await self._common_open().set(key, value)

    async def delete(self, key: str) -> None:
        logger.debug("redis delete", key=key)
        with self._common_guard():
            await self._common_open().delete(key)

    async def keys(self, prefix: str = "") -> AsyncIterator[str]:
        """Keys starting with `prefix`, streamed with SCAN — never KEYS, never materialized, unordered."""
        logger.debug("redis keys", prefix=prefix)
        with self._common_guard():
            async for key in self._common_open().scan_iter(match=f"{prefix}*"):
                yield cast("bytes", key).decode()
