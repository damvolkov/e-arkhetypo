"""tests/unit/e_infra/providers/drivers/cache/postgres: the durable cache over a database port that keeps a dict."""

from datetime import timedelta
from typing import TYPE_CHECKING

import anyio
import pytest

from e_infra.infra.config.providers.drivers.cache.postgres import CachePostgresSettings
from e_infra.infra.errors import CacheError
from e_infra.ports.cache import CachePort
from e_infra.providers.drivers.cache.postgres import CachePostgresDriver
from support.cache import cache

if TYPE_CHECKING:
    from unit.e_infra.conftest import Logs
    from unit.e_infra.providers.drivers.cache.conftest import FakeDatabase


async def test_cache_postgres_meets_the_cache_port(db: FakeDatabase) -> None:
    assert isinstance(cache(db), CachePort)


async def test_cache_postgres_opening_creates_the_table_and_logs(db: FakeDatabase, logs: Logs) -> None:
    async with cache(db):
        assert db.created == 1
    assert logs.at("info") == ["cache postgres opened", "cache postgres closed"]


async def test_cache_postgres_default_settings_come_from_the_composer(db: FakeDatabase) -> None:
    assert CachePostgresDriver(db, "unit", int)._conf == CachePostgresSettings()


async def test_cache_postgres_typed_values_by_namespace(db: FakeDatabase) -> None:
    async with cache(db) as numbers, cache(db, str, "other") as words:
        await numbers.put_many({"a": 1, "b": 2})
        await words.put("a", "text")
        await numbers.put("c", 3)
        assert await numbers.many(["a", "b", "z"]) == {"a": 1, "b": 2}
        assert (await numbers.get("c"), await numbers.get("z"), await numbers.many([])) == (3, None, {})
        assert await words.get("a") == "text"


async def test_cache_postgres_a_row_that_no_longer_decodes_is_a_miss_and_warned(db: FakeDatabase, logs: Logs) -> None:
    async with cache(db, str) as words:
        await words.put("a", "text")
    assert await cache(db, int).get("a") is None
    assert "cache postgres row skipped" in logs.at("warning")


async def test_cache_postgres_a_value_expires_after_its_ttl(db: FakeDatabase) -> None:
    async with cache(db, ttl=timedelta(milliseconds=30)) as ttl, cache(db, namespace="forever") as forever:
        await ttl.put("a", 1)
        await forever.put("a", 1)
        assert await ttl.get("a") == 1
        await anyio.sleep(0.06)
        assert (await ttl.get("a"), await forever.get("a")) == (None, 1)


async def test_cache_postgres_writing_nothing_asks_nothing(db: FakeDatabase) -> None:
    async with cache(db) as numbers:
        await numbers.put_many({})
    assert db.table == {}


async def test_cache_postgres_health_follows_the_database(db: FakeDatabase, logs: Logs) -> None:
    async with cache(db) as numbers:
        assert await numbers.health()
        db.down = True
        assert not await numbers.health()
    assert logs.at("warning") == ["cache postgres unhealthy"]


@pytest.mark.parametrize("call", ["get", "many", "put", "put_many", "open"])
async def test_cache_postgres_a_database_failure_is_a_cache_error_and_logged(
    db: FakeDatabase, logs: Logs, call: str
) -> None:
    numbers = cache(db)
    if call != "open":
        await numbers.__aenter__()
    db.down = True
    action = {
        "get": lambda: numbers.get("a"),
        "many": lambda: numbers.many(["a"]),
        "put": lambda: numbers.put("a", 1),
        "put_many": lambda: numbers.put_many({"a": 1}),
        "open": numbers.__aenter__,
    }[call]
    with pytest.raises(CacheError, match="connection reset"):
        await action()
    assert logs.at("error") == ["cache postgres failed"]
