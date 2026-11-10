"""tests/unit/e_infra/providers/drivers/cache/postgres_real: the durable cache over a real Postgres."""

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING

import anyio
import pytest

from e_infra.providers.drivers.cache.postgres import PostgresCacheDriver
from support.query import sql

if TYPE_CHECKING:
    from e_infra.providers.drivers.database.psqlpy import PsqlpyDriver

pytestmark = pytest.mark.integration


async def test_cache_postgres_roundtrip(pg: PsqlpyDriver) -> None:
    """Typed values by namespace; a row that no longer decodes is a miss; an expired one is skipped."""
    async with (
        PostgresCacheDriver(pg, "unit", int, ttl=None) as cache,
        PostgresCacheDriver(pg, "other", str, ttl=None) as other,
    ):
        await cache.put_many({"a": 1, "b": 2})
        await other.put("a", "text")
        await cache.put("c", 3)
        assert await cache.many(["a", "b", "z"]) == {"a": 1, "b": 2}
        assert (await cache.get("c"), await cache.get("z"), await cache.many([])) == (3, None, {})
        assert await other.get("a") == "text"
        assert await PostgresCacheDriver(pg, "other", int, ttl=None).get("a") is None
        assert await cache.health()


async def test_cache_postgres_expires(pg: PsqlpyDriver) -> None:
    async with PostgresCacheDriver(pg, "ttl", int, ttl=timedelta(milliseconds=50)) as cache:
        await cache.put("a", 1)
        await anyio.sleep(0.1)
        assert await cache.get("a") is None


async def test_cache_postgres_opened_at_once_makes_one_table(fleet: list[PsqlpyDriver]) -> None:
    """`CREATE TABLE IF NOT EXISTS` alone is not safe under concurrency: two creators collide on `pg_type`."""
    await fleet[0].execute(sql("DROP TABLE IF EXISTS cache"))
    caches = [PostgresCacheDriver(db, "race", int, ttl=None) for db in fleet]
    await asyncio.gather(*(cache.__aenter__() for cache in caches))
    await asyncio.gather(*(cache.put("k", n) for n, cache in enumerate(caches)))
    assert await fleet[0].row(sql("SELECT count(*) AS n FROM cache WHERE namespace = 'race'")) == {"n": 1}
