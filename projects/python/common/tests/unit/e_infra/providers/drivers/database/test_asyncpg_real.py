"""tests/unit/e_infra/providers/drivers/database/asyncpg_real: the asyncpg driver on a real Postgres — what no fake can say."""

from typing import TYPE_CHECKING

import pytest

from e_infra.infra.config.base import Secret
from e_infra.infra.config.providers.drivers.database.asyncpg import AsyncpgSettings
from e_infra.infra.errors import DatabaseError
from e_infra.ports.database import Vector
from e_infra.providers.drivers.database.asyncpg import AsyncpgDriver

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = pytest.mark.integration


@pytest.fixture
async def pg_asyncpg(database: str) -> AsyncIterator[AsyncpgDriver]:
    """An asyncpg driver over a fresh `adapters_asyncpg` schema holding one probe table, dropped after the test."""
    async with AsyncpgDriver(AsyncpgSettings(dsn=Secret(database), pool=2)) as driver:
        await driver.execute("CREATE EXTENSION IF NOT EXISTS vector")
        await driver.execute("DROP SCHEMA IF EXISTS adapters_asyncpg CASCADE")
        await driver.execute("CREATE SCHEMA adapters_asyncpg")
        await driver.execute("CREATE TABLE adapters_asyncpg.probe (id int PRIMARY KEY, label text, v vector(3))")
        yield driver
        await driver.execute("DROP SCHEMA adapters_asyncpg CASCADE")


async def test_asyncpg_real_statements_rows_as_dicts_and_a_vector(pg_asyncpg: AsyncpgDriver) -> None:
    await pg_asyncpg.many(
        "INSERT INTO adapters_asyncpg.probe (id, label, v) VALUES ($1, $2, $3)",
        [[1, "a", Vector((1.0, 0.0, 0.0))], [2, "b", Vector((0.0, 1.0, 0.0))]],
    )
    rows = await pg_asyncpg.fetch("SELECT id, label FROM adapters_asyncpg.probe ORDER BY id")
    nearest = await pg_asyncpg.row(
        "SELECT id FROM adapters_asyncpg.probe ORDER BY v <-> $1::vector LIMIT 1", [Vector((0.9, 0.1, 0.0))]
    )
    assert (rows, nearest) == ([{"id": 1, "label": "a"}, {"id": 2, "label": "b"}], {"id": 1})
    assert await pg_asyncpg.health()


async def test_asyncpg_real_transaction_commits_and_rolls_back(pg_asyncpg: AsyncpgDriver) -> None:
    async def failing() -> None:
        async with pg_asyncpg.transaction() as tx:
            await tx.execute("INSERT INTO adapters_asyncpg.probe (id) VALUES ($1)", [9])
            msg = "mine"
            raise ValueError(msg)

    async with pg_asyncpg.transaction() as tx:
        await tx.execute("INSERT INTO adapters_asyncpg.probe (id) VALUES ($1)", [1])
    with pytest.raises(ValueError, match="mine"):
        await failing()
    assert [row["id"] for row in await pg_asyncpg.fetch("SELECT id FROM adapters_asyncpg.probe")] == [1]


async def test_asyncpg_real_errors_are_database_errors(pg_asyncpg: AsyncpgDriver) -> None:
    with pytest.raises(DatabaseError):
        await pg_asyncpg.fetch("SELECT * FROM adapters_asyncpg.nowhere")
    with pytest.raises(DatabaseError):
        await AsyncpgDriver(AsyncpgSettings(dsn=Secret("postgresql://postgres:x@127.0.0.1:9/none"))).__aenter__()
