"""tests/unit/e_infra/providers/drivers/cache/postgres_real: the durable cache over a real Postgres."""

from datetime import timedelta
from typing import TYPE_CHECKING

import anyio
import pytest

from e_infra.infra.config.providers.drivers.cache.postgres import CachePostgresSettings
from e_infra.providers.drivers.cache.postgres import CachePostgresDriver

if TYPE_CHECKING:
    from e_infra.providers.drivers.database.psqlpy import PsqlpyDriver

pytestmark = pytest.mark.integration


async def test_cache_postgres_roundtrip(pg: PsqlpyDriver) -> None:
    """Typed values by namespace; a row that no longer decodes is a miss; an expired one is skipped."""
    async with CachePostgresDriver(pg, "unit", int) as cache, CachePostgresDriver(pg, "other", str) as other:
        await cache.put_many({"a": 1, "b": 2})
        await other.put("a", "text")
        await cache.put("c", 3)
        assert await cache.many(["a", "b", "z"]) == {"a": 1, "b": 2}
        assert (await cache.get("c"), await cache.get("z"), await cache.many([])) == (3, None, {})
        assert await other.get("a") == "text"
        assert await CachePostgresDriver(pg, "other", int).get("a") is None
        assert await cache.health()


async def test_cache_postgres_expires(pg: PsqlpyDriver) -> None:
    async with CachePostgresDriver(pg, "ttl", int, CachePostgresSettings(ttl=timedelta(milliseconds=50))) as cache:
        await cache.put("a", 1)
        await anyio.sleep(0.1)
        assert await cache.get("a") is None
