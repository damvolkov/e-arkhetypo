"""tests/unit/e_infra/providers/drivers/database/asyncpg: the asyncpg asyncpg_driver against a pool that holds no database."""

from datetime import timedelta
from typing import TYPE_CHECKING, Any

import anyio
import asyncpg
import pytest

from e_infra.infra.config.providers.drivers.database.asyncpg import AsyncpgSettings
from e_infra.infra.errors import DatabaseError
from e_infra.ports.database import DatabasePort, Vector
from e_infra.providers.drivers.database.asyncpg import AsyncpgDriver, AsyncpgTransaction

if TYPE_CHECKING:
    from support.asyncpg import FakeAsyncpgServer
    from unit.e_infra.conftest import Logs

DSN = "postgresql://u:p@db:5432/x"


##### LIFECYCLE #####
async def test_asyncpg_meets_the_port(asyncpg_driver: AsyncpgDriver) -> None:
    assert isinstance(asyncpg_driver, DatabasePort)


async def test_asyncpg_open_builds_the_pool_from_settings_and_close_closes_it(
    asyncpg_driver: AsyncpgDriver, asyncpg_server: FakeAsyncpgServer, logs: Logs
) -> None:
    async with asyncpg_driver:
        pool = asyncpg_server.pools[0]
        assert (pool.dsn, pool.kwargs) == (
            DSN,
            {"min_size": 2, "max_size": 4, "command_timeout": 3.0, "timeout": 3.0},
        )
        assert asyncpg_driver.pool is pool
    assert pool.closed
    assert logs.at("info") == ["asyncpg opened", "asyncpg closed"]
    await asyncpg_driver.__aexit__(None, None, None)


async def test_asyncpg_default_settings_come_from_the_composer(asyncpg_server: FakeAsyncpgServer) -> None:
    async with AsyncpgDriver():
        assert asyncpg_server.pools[0].kwargs["max_size"] == AsyncpgSettings().pool


async def test_asyncpg_unopened_calls_are_database_errors(asyncpg_driver: AsyncpgDriver) -> None:
    for call in (
        asyncpg_driver.execute("SELECT 1"),
        asyncpg_driver.fetch("SELECT 1"),
        asyncpg_driver.many("INSERT", [[1]]),
    ):
        with pytest.raises(DatabaseError, match="not open"):
            await call
    with pytest.raises(DatabaseError, match="not open"):
        _ = asyncpg_driver.pool


@pytest.mark.parametrize(
    "refusal",
    [OSError("connection refused"), asyncpg.PostgresConnectionError("server closed"), asyncpg.InterfaceError("bad")],
    ids=["os", "postgres", "interface"],
)
async def test_asyncpg_open_refused_is_a_database_error(
    asyncpg_driver: AsyncpgDriver, asyncpg_server: FakeAsyncpgServer, logs: Logs, refusal: BaseException
) -> None:
    asyncpg_server.refuse = refusal
    with pytest.raises(DatabaseError):
        await asyncpg_driver.__aenter__()
    assert logs.at("error") == ["asyncpg failed"]
    assert not await asyncpg_driver.health()


async def test_asyncpg_open_that_never_answers_times_out(
    asyncpg_server: FakeAsyncpgServer, monkeypatch: pytest.MonkeyPatch, logs: Logs
) -> None:
    async def never(dsn: str, **kwargs: Any) -> None:
        await anyio.sleep_forever()

    monkeypatch.setattr(asyncpg, "create_pool", never)
    with pytest.raises(DatabaseError, match="open timed out"):
        await AsyncpgDriver(AsyncpgSettings(timeout=timedelta(milliseconds=50))).__aenter__()
    assert logs.at("error") == ["asyncpg open timed out"]


async def test_asyncpg_close_that_never_returns_terminates_the_pool(
    asyncpg_server: FakeAsyncpgServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def never() -> None:
        await anyio.sleep_forever()

    slow = AsyncpgDriver(AsyncpgSettings(timeout=timedelta(milliseconds=50)))
    await slow.__aenter__()
    pool = asyncpg_server.pools[0]
    monkeypatch.setattr(pool, "close", never)
    with pytest.raises(DatabaseError, match="close timed out"):
        await slow.__aexit__(None, None, None)
    assert pool.terminated


##### HEALTH #####
async def test_asyncpg_health_true_when_a_query_answers(
    asyncpg_driver: AsyncpgDriver, asyncpg_server: FakeAsyncpgServer
) -> None:
    async with asyncpg_driver:
        assert await asyncpg_driver.health()
    assert asyncpg_server.sql() == ["SELECT 1"]


async def test_asyncpg_health_false_and_warned_when_the_query_fails(
    asyncpg_driver: AsyncpgDriver, asyncpg_server: FakeAsyncpgServer, logs: Logs
) -> None:
    asyncpg_server.failures["SELECT 1"] = asyncpg.InterfaceError("pool is closing")
    async with asyncpg_driver:
        assert not await asyncpg_driver.health()
    assert "asyncpg unhealthy" in logs.at("warning")


async def test_asyncpg_health_false_when_never_opened(asyncpg_driver: AsyncpgDriver) -> None:
    assert not await asyncpg_driver.health()


##### STATEMENTS #####
async def test_asyncpg_statements_run_with_their_parameters(
    asyncpg_driver: AsyncpgDriver, asyncpg_server: FakeAsyncpgServer
) -> None:
    asyncpg_server.answers["FROM t"] = [{"id": 1}, {"id": 2}]
    async with asyncpg_driver:
        await asyncpg_driver.execute("DELETE FROM t WHERE id = $1", [7])
        rows = await asyncpg_driver.fetch("SELECT id FROM t", [])
        first = await asyncpg_driver.row("SELECT id FROM t")
        await asyncpg_driver.many("INSERT INTO t VALUES ($1)", [[1], [2]])
    assert (rows, first) == ([{"id": 1}, {"id": 2}], {"id": 1})
    assert asyncpg_server.statements == [
        ("DELETE FROM t WHERE id = $1", (7,)),
        ("SELECT id FROM t", ()),
        ("SELECT id FROM t", ()),
        ("INSERT INTO t VALUES ($1)", (1,)),
        ("INSERT INTO t VALUES ($1)", (2,)),
    ]
    assert asyncpg_server.held == 0


async def test_asyncpg_row_of_nothing_is_none(asyncpg_driver: AsyncpgDriver) -> None:
    async with asyncpg_driver:
        assert await asyncpg_driver.row("SELECT 1 WHERE false") is None


async def test_asyncpg_vector_binds_as_pgvectors_text_form(
    asyncpg_driver: AsyncpgDriver, asyncpg_server: FakeAsyncpgServer
) -> None:
    async with asyncpg_driver:
        await asyncpg_driver.execute("INSERT INTO v VALUES ($1, $2)", [Vector((0.1, 0.25)), "plain"])
    assert asyncpg_server.statements[0][1] == ("[0.1,0.25]", "plain")


##### TRANSACTION #####
async def test_asyncpg_transaction_commits_on_a_clean_exit(
    asyncpg_driver: AsyncpgDriver, asyncpg_server: FakeAsyncpgServer
) -> None:
    asyncpg_server.answers["FROM t"] = [{"id": 1}]
    async with asyncpg_driver, asyncpg_driver.transaction() as tx:
        await tx.execute("UPDATE t SET x = $1", [1])
        assert await tx.fetch("SELECT id FROM t") == [{"id": 1}]
        assert await tx.row("SELECT id FROM t") == {"id": 1}
        await tx.many("INSERT INTO t VALUES ($1)", [[1], [2]])
        assert isinstance(tx, AsyncpgTransaction)
        async with tx.transaction() as nested:
            assert nested is tx
    assert asyncpg_server.transactions == ["begin", "commit"]
    assert (len(asyncpg_server.statements), asyncpg_server.held) == (5, 0)


async def test_asyncpg_transaction_rolls_back_on_a_raise_and_lets_it_through(
    asyncpg_driver: AsyncpgDriver, asyncpg_server: FakeAsyncpgServer
) -> None:
    async def mine() -> None:
        async with asyncpg_driver.transaction() as tx:
            await tx.execute("UPDATE t SET x = 1")
            msg = "mine"
            raise ValueError(msg)

    async with asyncpg_driver:
        with pytest.raises(ValueError, match="mine"):
            await mine()
    assert asyncpg_server.transactions == ["begin", "rollback"]


##### ERRORS — asyncpg's own never leave #####
@pytest.mark.parametrize("method", ["execute", "fetch", "row", "many"])
@pytest.mark.parametrize(
    "failure",
    [asyncpg.UndefinedTableError("no such table"), asyncpg.InterfaceError("pool is closing"), OSError("reset")],
    ids=["postgres", "interface", "os"],
)
async def test_asyncpg_errors_are_translated_and_logged(
    asyncpg_driver: AsyncpgDriver, asyncpg_server: FakeAsyncpgServer, logs: Logs, method: str, failure: BaseException
) -> None:
    asyncpg_server.failures["BOOM"] = failure
    args: Any = [[1]] if method == "many" else ()
    async with asyncpg_driver:
        with pytest.raises(DatabaseError) as caught:
            await getattr(asyncpg_driver, method)("BOOM", args)
    assert caught.value.__cause__ is failure
    assert logs.at("error") == ["asyncpg failed"]


async def test_asyncpg_transaction_errors_are_translated(
    asyncpg_driver: AsyncpgDriver, asyncpg_server: FakeAsyncpgServer
) -> None:
    asyncpg_server.failures["BOOM"] = asyncpg.UndefinedTableError("no such table")
    async with asyncpg_driver:
        with pytest.raises(DatabaseError):
            async with asyncpg_driver.transaction() as tx:
                await tx.fetch("BOOM")
        with pytest.raises(DatabaseError):
            async with asyncpg_driver.transaction() as tx:
                await tx.execute("BOOM")
    assert asyncpg_server.transactions == ["begin", "rollback", "begin", "rollback"]


##### CANCELLATION #####
async def test_asyncpg_a_cancelled_call_is_not_swallowed_and_gives_its_connection_back(
    asyncpg_driver: AsyncpgDriver, asyncpg_server: FakeAsyncpgServer
) -> None:
    asyncpg_server.hang = "SLOW"
    async with asyncpg_driver:
        with anyio.move_on_after(0.05) as scope:
            await asyncpg_driver.fetch("SLOW")
        assert scope.cancelled_caught
    assert asyncpg_server.held == 0


##### DEDICATED CONNECTIONS — what a library that owns its client rides #####
async def test_asyncpg_dedicated_connection_is_opened_outside_the_pool_and_closed_on_exit(
    asyncpg_driver: AsyncpgDriver, asyncpg_server: FakeAsyncpgServer
) -> None:
    async with asyncpg_driver, asyncpg_driver.connection():
        opened = asyncpg_server.connections[0]
        assert (opened.dsn, opened.kwargs, asyncpg_server.dedicated) == (DSN, {"timeout": 3.0}, 1)
    assert (opened.closed, asyncpg_server.dedicated) == (True, 0)


async def test_asyncpg_dedicated_connection_closes_when_its_block_fails(
    asyncpg_driver: AsyncpgDriver, asyncpg_server: FakeAsyncpgServer
) -> None:
    async def fails() -> None:
        async with asyncpg_driver.connection():
            msg = "block"
            raise ValueError(msg)

    with pytest.raises(ValueError, match="block"):
        await fails()
    assert asyncpg_server.dedicated == 0


async def test_asyncpg_dedicated_connection_refused_is_a_database_error(
    asyncpg_driver: AsyncpgDriver, asyncpg_server: FakeAsyncpgServer
) -> None:
    asyncpg_server.refuse = OSError("connection refused")
    with pytest.raises(DatabaseError, match="refused"):
        async with asyncpg_driver.connection():
            pass
