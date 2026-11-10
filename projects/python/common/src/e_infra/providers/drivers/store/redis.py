"""providers/drivers/store/redis: a store over redis.asyncio (the official client, async driver) — bytes in, bytes out."""

from contextlib import contextmanager
from typing import TYPE_CHECKING, ClassVar, Self

import redis.asyncio as redis
from redis.exceptions import RedisError

from e_infra.infra.errors import ProviderError, StoreError
from e_infra.infra.logger import logger
from e_infra.ports.provider import Isolation, Locality, Opened, ProviderSpec, Workload

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Generator
    from datetime import timedelta

    from pydantic import RedisDsn, Secret


##### TYPES #####
class RedisDriver:
    """Thin KV over a redis connection pool; bytes in, bytes out — decode stays off."""

    spec: ClassVar[ProviderSpec] = ProviderSpec(
        "redis", Locality.REMOTE, Workload.IO_BOUND, Isolation.LOOP, pooled=True
    )
    client = Opened[redis.Redis](StoreError)

    def __init__(self, *, url: Secret[RedisDsn], pool: int, timeout: timedelta) -> None:
        self._url, self._pool, self._timeout = url, pool, timeout
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

    ############################################################

    ##### PUBLIC #####

    async def __aenter__(self) -> Self:
        timeout = self._timeout.total_seconds()
        self._client = redis.from_url(
            str(self._url.get_secret_value()),
            max_connections=self._pool,
            socket_timeout=timeout,
            socket_connect_timeout=timeout,
        )
        logger.info("redis opened", pool=self._pool)
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
                await self.client.ping()
        except ProviderError as error:
            logger.warning("redis unhealthy", error=str(error))
            raise
        return True

    async def get(self, key: str) -> bytes | None:
        logger.debug("redis get", key=key)
        with self._common_guard():
            match await self.client.get(key):
                ### decode_responses is off, so redis hands bytes; its stub still allows str.
                case str() as text:
                    return text.encode()
                case found:
                    return found

    async def set(self, key: str, value: bytes) -> None:
        logger.debug("redis set", key=key, size=len(value))
        with self._common_guard():
            await self.client.set(key, value)

    async def delete(self, key: str) -> None:
        logger.debug("redis delete", key=key)
        with self._common_guard():
            await self.client.delete(key)

    async def keys(self, prefix: str | None = None) -> AsyncIterator[str]:
        """Keys starting with `prefix`, streamed with SCAN — never KEYS, never materialized, unordered."""
        logger.debug("redis keys", prefix=prefix)
        with self._common_guard():
            async for key in self.client.scan_iter(match=None if prefix is None else f"{prefix}*"):
                yield key.decode()
