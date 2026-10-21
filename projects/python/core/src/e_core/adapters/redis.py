"""adapters/redis: StoreAdapter over redis.asyncio (the official client, async driver)."""

from typing import TYPE_CHECKING, ClassVar, cast

import redis.asyncio as redis

from e_core.adapters.base import StoreAdapter
from e_core.core.settings import settings as st

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from e_core.core.settings.redis import RedisSettings


##### TYPES #####
class RedisAdapter(StoreAdapter):
    """Thin KV over a redis connection pool; bytes in, bytes out — decode stays off."""

    name: ClassVar[str] = "redis"

    def __init__(self, settings: RedisSettings | None = None) -> None:
        ### the default is read on call, not at import: the settings singleton stays lazy.
        self._url = (st.redis if settings is None else settings).redis_url
        self._client: redis.Redis | None = None

    ##### PRIVATE METHODS #####

    def _common_connected(self) -> redis.Redis:
        match self._client:
            case None:
                msg = "RedisAdapter not connected: the lifespan opens it, handlers never do"
                raise RuntimeError(msg)
            case client:
                return client

    ############################################################

    ##### PUBLIC #####

    async def connect(self) -> None:
        self._client = redis.from_url(self._url)

    async def close(self) -> None:
        match self._client:
            case None:
                return
            case client:
                await client.aclose()
                self._client = None

    async def get(self, key: str) -> bytes | None:
        return cast("bytes | None", await self._common_connected().get(key))

    async def set(self, key: str, value: bytes) -> None:
        await self._common_connected().set(key, value)

    async def delete(self, key: str) -> None:
        await self._common_connected().delete(key)

    async def keys(self, prefix: str = "") -> AsyncIterator[str]:
        """Keys starting with `prefix`, streamed with SCAN — never KEYS, never materialized, unordered."""
        async for key in self._common_connected().scan_iter(match=f"{prefix}*"):
            yield cast("bytes", key).decode()
