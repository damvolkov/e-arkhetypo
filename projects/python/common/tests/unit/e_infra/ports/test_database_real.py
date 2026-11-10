"""tests/unit/e_infra/ports/database: `DatabasePort` and `ListenPort` as a contract on a real Postgres.

Every test runs on both drivers (the `db` fixture), so the twins answer the same rows, types, scopes, refusals and
notifications."""

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import anyio
import pytest
import pytest_asyncio

from e_infra.infra.errors import DatabaseError
from e_infra.ports.database import DatabasePort, ListenPort, Vector
from e_infra.providers.drivers.database.asyncpg import AsyncpgDriver
from e_infra.providers.drivers.database.psqlpy import PsqlpyDriver
from unit.e_infra.conftest import DSN, asyncpg_args, create, psqlpy_args

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = pytest.mark.integration

TYPES = (
    "SELECT '{\"a\": 1}'::jsonb AS j, '7d5c2f3e-0d1b-4c5a-9f6e-1a2b3c4d5e6f'::uuid AS u, now() AS t, 1.5::float8 AS f, "
    "2::numeric AS n, ARRAY['x'] AS a, true AS b, 3::int2 AS s, 'x'::bytea AS by, NULL::text AS none"
)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def database(worker_id: str) -> str:
    """A database of the contract's own beside POSTGRES_TEST_DSN's; no server is an error, never a skip."""
    return await create(f"{DSN}_ports_{worker_id}")


@pytest.fixture(params=["psqlpy", "asyncpg"])
async def db(request: pytest.FixtureRequest, database: str) -> AsyncIterator[PsqlpyDriver | AsyncpgDriver]:
    """Each driver open on the contract's database, its `twin` table dropped before and after."""
    driver = (
        PsqlpyDriver(**psqlpy_args(database, pool=2))
        if request.param == "psqlpy"
        else AsyncpgDriver(**asyncpg_args(database, pool=2))
    )
    async with driver:
        await driver.execute("DROP TABLE IF EXISTS twin")
        yield driver
        await driver.execute("DROP TABLE IF EXISTS twin")


async def test_database_meets_both_ports(db: PsqlpyDriver | AsyncpgDriver) -> None:
    assert (isinstance(db, DatabasePort), isinstance(db, ListenPort)) == (True, True)


async def test_database_types_are_one_shape(db: PsqlpyDriver | AsyncpgDriver) -> None:
    found = await db.row(TYPES)
    assert found is not None
    assert {key: type(value) for key, value in found.items()} == {
        "j": dict, "u": str, "t": datetime, "f": float, "n": Decimal, "a": list, "b": bool, "s": int, "by": bytes,
        "none": type(None),
    }  # fmt: skip
    assert (found["j"], found["u"], found["t"].tzinfo is not None) == (
        {"a": 1},
        "7d5c2f3e-0d1b-4c5a-9f6e-1a2b3c4d5e6f",
        True,
    )


async def test_database_parameters_bind_alike(db: PsqlpyDriver | AsyncpgDriver) -> None:
    found = await db.row(
        "SELECT $1::jsonb AS j, $2::text[] AS a, $3::bigint AS b, $4::bytea AS by, ($5::vector)::real[] AS v",
        [{"y": [1, 2]}, ["a", "b"], 2**40, b"\x00\x01", Vector((0.5, 1.0, 2.0))],
    )
    assert found == {"j": {"y": [1, 2]}, "a": ["a", "b"], "b": 2**40, "by": b"\x00\x01", "v": [0.5, 1.0, 2.0]}


async def test_database_many_and_script(db: PsqlpyDriver | AsyncpgDriver) -> None:
    await db.script("CREATE TABLE twin (k int PRIMARY KEY, v text); CREATE INDEX twin_v ON twin (v)")
    await db.many("INSERT INTO twin VALUES ($1, $2)", [[1, "a"], [2, "b"]])
    await db.execute("-- a statement of comments only is no error")
    assert await db.fetch("SELECT k, v FROM twin ORDER BY k") == [{"k": 1, "v": "a"}, {"k": 2, "v": "b"}]


async def test_database_transaction_commits_or_rolls_back(db: PsqlpyDriver | AsyncpgDriver) -> None:
    await db.execute("CREATE TABLE twin (k int PRIMARY KEY)")
    async with db.transaction() as tx:
        await tx.execute("INSERT INTO twin VALUES (1)")

    async def undone() -> None:
        async with db.transaction() as tx:
            await tx.execute("INSERT INTO twin VALUES (2)")
            await tx.execute("INSERT INTO twin VALUES (2)")

    with pytest.raises(DatabaseError):
        await undone()
    assert await db.fetch("SELECT k FROM twin") == [{"k": 1}]


async def test_database_nested_scopes_are_the_outer_one(db: PsqlpyDriver | AsyncpgDriver) -> None:
    """A transaction or a connection opened inside a scope is that scope: its statements land on the same connection."""
    async with db.transaction() as tx, tx.transaction() as inner, inner.connection() as held:
        await held.execute("CREATE TEMP TABLE scoped (k int)")
        await held.script("INSERT INTO scoped VALUES (1); INSERT INTO scoped VALUES (2)")
        await held.many("INSERT INTO scoped VALUES ($1)", [[3]])
        assert (await tx.row("SELECT count(*)::int AS n FROM scoped"), held is inner is tx) == ({"n": 3}, True)


async def test_database_connection_holds_a_session_lock(db: PsqlpyDriver | AsyncpgDriver) -> None:
    """Lock and unlock on one connection: what a schema lock needs, never escaping across a pool."""
    async with db.connection() as held:
        await held.execute("SELECT pg_advisory_lock($1)", [4242])
        unlocked = await held.row("SELECT pg_advisory_unlock($1) AS ok", [4242])
    assert unlocked == {"ok": True}


async def test_database_unique_violation_names_its_state(db: PsqlpyDriver | AsyncpgDriver) -> None:
    await db.execute("CREATE TABLE twin (k int CONSTRAINT twin_k PRIMARY KEY)")
    await db.execute("INSERT INTO twin VALUES (1)")
    with pytest.raises(DatabaseError) as refused:
        await db.execute("INSERT INTO twin VALUES (1)")
    assert (refused.value.sqlstate, refused.value.constraint_name) == ("23505", "twin_k")


async def test_database_other_refusals_are_database_errors(db: PsqlpyDriver | AsyncpgDriver) -> None:
    with pytest.raises(DatabaseError, match="nowhere"):
        await db.fetch("SELECT * FROM nowhere")


async def test_database_listen_fans_out_and_unlistens(db: PsqlpyDriver | AsyncpgDriver) -> None:
    heard: list[tuple[str, str]] = []

    def first(payload: str) -> None:
        heard.append(("first", payload))

    def second(payload: str) -> None:
        heard.append(("second", payload))

    async def told(payload: str, count: int) -> None:
        await db.execute("SELECT pg_notify($1, $2)", ["twins", payload])
        with anyio.fail_after(5):
            _ = [await anyio.sleep(0.02) for _ in iter(lambda: len(heard) >= count, True)]

    await db.listen("twins", first)
    await db.listen("twins", second)
    await told("both", 2)
    await db.unlisten("twins", first)
    await told("one", 3)
    await db.unlisten("twins", second)
    await db.execute("SELECT pg_notify($1, $2)", ["twins", "none"])
    await anyio.sleep(0.2)
    assert sorted(heard) == [("first", "both"), ("second", "both"), ("second", "one")]


async def test_database_provision_finds_it_there(db: PsqlpyDriver | AsyncpgDriver) -> None:
    assert await db.provision() is False
