from contextlib import suppress

import pytest

from e_infra.adapters.base import PingError
from e_infra.adapters.ports import SqlPort, Vector
from e_infra.adapters.postgres import PostgresAdapter, PostgresError
from e_infra.infra.config.base import Secret
from e_infra.infra.config.postgres import PostgresSettings

pytestmark = pytest.mark.db


async def test_postgres_execute_fetch(pg: PostgresAdapter) -> None:
    await pg.execute("INSERT INTO adapters.probe (id, label) VALUES ($1, $2)", [1, "one"])
    assert await pg.fetch("SELECT id, label FROM adapters.probe") == [{"id": 1, "label": "one"}]


async def test_postgres_row(pg: PostgresAdapter) -> None:
    assert await pg.row("SELECT id FROM adapters.probe") is None
    await pg.many("INSERT INTO adapters.probe (id, label) VALUES ($1, $2)", [[1, "one"], [2, "two"]])
    assert await pg.row("SELECT id, label FROM adapters.probe ORDER BY id") == {"id": 1, "label": "one"}


async def test_postgres_vector(pg: PostgresAdapter) -> None:
    await pg.many(
        "INSERT INTO adapters.probe (id, v) VALUES ($1, $2)",
        [[1, Vector((1.0, 0.0, 0.0))], [2, Vector((0.0, 1.0, 0.0))]],
    )
    rows = await pg.fetch(
        "SELECT id, 1 - (v <=> $1) AS score FROM adapters.probe ORDER BY v <=> $1", [Vector((0.9, 0.1, 0.0))]
    )
    assert [row["id"] for row in rows] == [1, 2]
    assert rows[0]["score"] == pytest.approx(0.9939, abs=1e-4)


async def test_postgres_transaction_commit(pg: PostgresAdapter) -> None:
    async with pg.transaction() as tx:
        await tx.execute("INSERT INTO adapters.probe (id, label) VALUES ($1, $2)", [1, "one"])
        await tx.many("INSERT INTO adapters.probe (id, label) VALUES ($1, $2)", [[2, "two"]])
        assert await tx.row("SELECT count(*) AS n FROM adapters.probe") == {"n": 2}
    assert await pg.fetch("SELECT id FROM adapters.probe ORDER BY id") == [{"id": 1}, {"id": 2}]


async def test_postgres_transaction_rollback(pg: PostgresAdapter) -> None:
    with suppress(ZeroDivisionError):
        async with pg.transaction() as tx:
            await tx.execute("INSERT INTO adapters.probe (id) VALUES ($1)", [1])
            _ = 1 / 0
    assert await pg.fetch("SELECT id FROM adapters.probe") == []


async def test_postgres_transaction_nested(pg: PostgresAdapter) -> None:
    async with pg.transaction() as tx, tx.transaction() as inner:
        assert inner is tx
        assert isinstance(inner, SqlPort)


async def test_postgres_unconnected(pg_settings: PostgresSettings) -> None:
    adapter = PostgresAdapter(pg_settings)
    with pytest.raises(PostgresError):
        await adapter.fetch("SELECT 1")


async def test_postgres_close_twice(pg_settings: PostgresSettings) -> None:
    adapter = PostgresAdapter(pg_settings)
    await adapter.connect()
    await adapter.connect()
    assert await adapter.row("SELECT 1 AS one") == {"one": 1}
    await adapter.close()
    await adapter.close()
    with pytest.raises(PostgresError):
        await adapter.execute("SELECT 1")


async def test_postgres_provision(pg_settings: PostgresSettings) -> None:
    """A missing database is created, once; the second call finds it."""
    head, _, base = pg_settings.dsn.get_secret_value().rpartition("/")
    name = f"{base}_provision"
    adapter = PostgresAdapter(pg_settings.model_copy(update={"dsn": Secret(f"{head}/{name}")}))
    async with PostgresAdapter(pg_settings) as admin:
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}"')
        try:
            assert (await adapter.provision(), await adapter.provision()) == (True, False)
            assert await admin.row("SELECT 1 AS one FROM pg_database WHERE datname = $1", [name]) == {"one": 1}
        finally:
            await admin.execute(f'DROP DATABASE IF EXISTS "{name}"')


async def test_postgres_provision_race(pg_settings: PostgresSettings) -> None:
    """A create that fails over a database now there lost a race to a twin: not an error. One that fails over none is."""
    adapter = PostgresAdapter(pg_settings)
    async with PostgresAdapter(pg_settings) as admin, admin._common_pool().acquire() as connection:
        existing = pg_settings.dsn.get_secret_value().rpartition("/")[2]
        assert await adapter._provision_twin(connection, existing) is False
        with pytest.raises(PostgresError, match="could not be created"):
            await adapter._provision_create(connection, "")


async def test_postgres_provision_unreachable(pg_settings: PostgresSettings) -> None:
    down = pg_settings.model_copy(update={"dsn": Secret("postgresql://postgres:postgres@127.0.0.1:1/x")})
    with pytest.raises(PostgresError, match="unreachable"):
        await PostgresAdapter(down).provision()


async def test_postgres_ping(pg: PostgresAdapter) -> None:
    await pg.ping()


async def test_postgres_ping_down() -> None:
    """A server nothing listens for: `SELECT 1` never runs, the adapter is down by name."""
    settings = PostgresSettings(dsn=Secret("postgresql://postgres:postgres@127.0.0.1:9/none"), pool=2)
    async with PostgresAdapter(settings) as adapter:
        with pytest.raises(PingError, match=r"^postgres: "):
            await adapter.ping()
