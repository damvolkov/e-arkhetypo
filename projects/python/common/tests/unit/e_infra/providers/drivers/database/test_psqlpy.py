"""tests/unit/e_infra/providers/drivers/database/psqlpy: the psqlpy driver against a pool that holds no database."""

from datetime import timedelta
from typing import TYPE_CHECKING, Any

import anyio
import pytest
from psqlpy.extra_types import PgVector

from e_infra.infra.config.base import Secret
from e_infra.infra.config.providers.drivers.database.psqlpy import PsqlpySettings
from e_infra.infra.errors import DatabaseError
from e_infra.ports.database import DatabasePort, Vector
from e_infra.providers.drivers.database.psqlpy import FOUND, PsqlpyDriver, PsqlpyTransaction

if TYPE_CHECKING:
    from psqlpy.exceptions import Error as PsqlError

    from support.psqlpy import FakePsqlpyServer
    from unit.e_infra.conftest import Logs


##### LIFECYCLE #####
async def test_psqlpy_meets_the_port(driver: PsqlpyDriver) -> None:
    assert isinstance(driver, DatabasePort)


async def test_psqlpy_open_builds_the_pool_from_settings_and_close_closes_it(
    driver: PsqlpyDriver, psqlpy: FakePsqlpyServer, logs: Logs
) -> None:
    async with driver:
        assert psqlpy.pools[0].kwargs == {
            "dsn": "postgresql://u:p@db:5432/x",
            "max_db_pool_size": 4,
            "connect_timeout_sec": 30,
        }
        assert not psqlpy.pools[0].closed
    assert psqlpy.pools[0].closed
    assert logs.at("info") == ["psqlpy opened", "psqlpy closed"]
    await driver.__aexit__(None, None, None)


async def test_psqlpy_pool_never_drops_below_psqlpys_floor(psqlpy: FakePsqlpyServer) -> None:
    async with PsqlpyDriver(PsqlpySettings(pool=1)):
        assert psqlpy.pools[0].kwargs["max_db_pool_size"] == 2


async def test_psqlpy_default_settings_come_from_the_composer(psqlpy: FakePsqlpyServer) -> None:
    async with PsqlpyDriver():
        assert psqlpy.pools[0].kwargs["max_db_pool_size"] == PsqlpySettings().pool


async def test_psqlpy_unopened_calls_are_database_errors(driver: PsqlpyDriver) -> None:
    for call in (driver.execute("SELECT 1"), driver.fetch("SELECT 1"), driver.many("INSERT", [[1]])):
        with pytest.raises(DatabaseError, match="not open"):
            await call


##### HEALTH #####
async def test_psqlpy_health_true_when_a_query_answers(driver: PsqlpyDriver, psqlpy: FakePsqlpyServer) -> None:
    async with driver:
        assert await driver.health()
    assert psqlpy.sql() == ["SELECT 1"]


async def test_psqlpy_health_false_and_warned_when_the_query_fails(
    driver: PsqlpyDriver, psqlpy: FakePsqlpyServer, broken: PsqlError, logs: Logs
) -> None:
    psqlpy.failures["SELECT 1"] = broken
    async with driver:
        assert not await driver.health()
    assert "psqlpy unhealthy" in logs.at("warning")


async def test_psqlpy_health_false_when_never_opened(driver: PsqlpyDriver, logs: Logs) -> None:
    assert not await driver.health()
    assert logs.at("warning") == ["psqlpy unhealthy"]


##### STATEMENTS #####
async def test_psqlpy_statements_run_with_their_parameters(driver: PsqlpyDriver, psqlpy: FakePsqlpyServer) -> None:
    psqlpy.answers["FROM t"] = [{"id": 1}, {"id": 2}]
    async with driver:
        await driver.execute("DELETE FROM t WHERE id = $1", [7])
        rows = await driver.fetch("SELECT id FROM t", [])
        first = await driver.row("SELECT id FROM t")
        await driver.many("INSERT INTO t VALUES ($1)", [[1], [2]])
    assert (rows, first) == ([{"id": 1}, {"id": 2}], {"id": 1})
    assert psqlpy.statements == [
        ("DELETE FROM t WHERE id = $1", [7]),
        ("SELECT id FROM t", []),
        ("SELECT id FROM t", []),
        ("INSERT INTO t VALUES ($1)", [1]),
        ("INSERT INTO t VALUES ($1)", [2]),
    ]


async def test_psqlpy_row_of_nothing_is_none(driver: PsqlpyDriver) -> None:
    async with driver:
        assert await driver.row("SELECT 1 WHERE false") is None


async def test_psqlpy_vector_binds_as_a_pgvector(driver: PsqlpyDriver, psqlpy: FakePsqlpyServer) -> None:
    async with driver:
        await driver.execute("INSERT INTO v VALUES ($1, $2)", [Vector((0.1, 0.2)), "plain"])
    bound = psqlpy.statements[0][1]
    assert (type(bound[0]), bound[1]) == (PgVector, "plain")


##### TRANSACTION #####
async def test_psqlpy_transaction_commits_on_a_clean_exit(driver: PsqlpyDriver, psqlpy: FakePsqlpyServer) -> None:
    psqlpy.answers["FROM t"] = [{"id": 1}]
    async with driver, driver.transaction() as tx:
        await tx.execute("UPDATE t SET x = $1", [1])
        assert await tx.fetch("SELECT id FROM t") == [{"id": 1}]
        assert await tx.row("SELECT id FROM t") == {"id": 1}
        await tx.many("INSERT INTO t VALUES ($1)", [[1], [2]])
        assert isinstance(tx, PsqlpyTransaction)
        async with tx.transaction() as nested:
            assert nested is tx
    assert psqlpy.transactions == ["begin", "commit"]
    assert len(psqlpy.statements) == 5


async def test_psqlpy_transaction_rolls_back_on_a_raise_and_lets_it_through(
    driver: PsqlpyDriver, psqlpy: FakePsqlpyServer
) -> None:
    async def mine() -> None:
        async with driver.transaction() as tx:
            await tx.execute("UPDATE t SET x = 1")
            msg = "mine"
            raise ValueError(msg)

    async with driver:
        with pytest.raises(ValueError, match="mine"):
            await mine()
    assert psqlpy.transactions == ["begin", "rollback"]


##### ERRORS — psqlpy's own never leave #####
@pytest.mark.parametrize("method", ["execute", "fetch", "row", "many"])
async def test_psqlpy_errors_are_translated_and_logged(
    driver: PsqlpyDriver, psqlpy: FakePsqlpyServer, broken: PsqlError, logs: Logs, method: str
) -> None:
    psqlpy.failures["BOOM"] = broken
    args: Any = [[1]] if method == "many" else ()
    async with driver:
        with pytest.raises(DatabaseError, match="connection reset") as caught:
            await getattr(driver, method)("BOOM", args)
    assert caught.value.__cause__ is broken
    assert logs.at("error") == ["psqlpy failed"]


async def test_psqlpy_transaction_errors_are_translated(
    driver: PsqlpyDriver, psqlpy: FakePsqlpyServer, broken: PsqlError
) -> None:
    psqlpy.failures["BOOM"] = broken
    async with driver:
        with pytest.raises(DatabaseError):
            async with driver.transaction() as tx:
                await tx.fetch("BOOM")
        with pytest.raises(DatabaseError):
            async with driver.transaction() as tx:
                await tx.execute("BOOM")
    assert psqlpy.transactions == ["begin", "rollback", "begin", "rollback"]


##### CANCELLATION #####
async def test_psqlpy_a_cancelled_call_gives_its_connection_back(
    driver: PsqlpyDriver, psqlpy: FakePsqlpyServer
) -> None:
    psqlpy.hang = "SLOW"
    async with driver:
        with anyio.move_on_after(0.05) as scope:
            await driver.fetch("SLOW")
        assert scope.cancelled_caught
    assert psqlpy.held == 0


##### PROVISION #####
@pytest.mark.parametrize(
    ("found", "created"), [([], True), ([{"?column?": 1}], False)], ids=["missing", "already-there"]
)
async def test_psqlpy_provision_creates_a_missing_database_on_the_maintenance_one(
    driver: PsqlpyDriver, psqlpy: FakePsqlpyServer, logs: Logs, found: list[dict[str, int]], created: bool
) -> None:
    psqlpy.answers[FOUND] = found
    assert await driver.provision() is created
    admin = psqlpy.pools[-1]
    assert (admin.kwargs["dsn"], admin.closed) == ("postgresql://u:p@db:5432/postgres", True)
    assert psqlpy.statements[0] == (FOUND, ["x"])
    assert ('CREATE DATABASE "x"' in psqlpy.sql()) is created
    assert (logs.at("info") == ["psqlpy database created"]) is created


async def test_psqlpy_provision_loses_the_race_without_error(
    driver: PsqlpyDriver, psqlpy: FakePsqlpyServer, broken: PsqlError
) -> None:
    """A twin created it between the look and the CREATE: not this call's creation, and no failure."""
    looks = iter([[], [{"?column?": 1}]])
    psqlpy.answers[FOUND] = lambda: next(looks)
    psqlpy.failures["CREATE DATABASE"] = broken
    assert await driver.provision() is False


async def test_psqlpy_provision_failing_for_real_is_a_database_error(
    driver: PsqlpyDriver, psqlpy: FakePsqlpyServer, broken: PsqlError
) -> None:
    psqlpy.answers[FOUND] = []
    psqlpy.failures["CREATE DATABASE"] = broken
    with pytest.raises(DatabaseError, match="could not be created"):
        await driver.provision()


async def test_psqlpy_provision_of_an_unreachable_server_is_a_database_error(
    driver: PsqlpyDriver, psqlpy: FakePsqlpyServer, broken: PsqlError, logs: Logs
) -> None:
    psqlpy.refuse = broken
    with pytest.raises(DatabaseError, match="unreachable"):
        await driver.provision()
    assert psqlpy.pools[-1].closed
    assert logs.at("error") == ["psqlpy provision failed"]


async def test_psqlpy_pool_timeout_reaches_the_connect_bound(psqlpy: FakePsqlpyServer) -> None:
    async with PsqlpyDriver(PsqlpySettings(dsn=Secret("postgresql://h/x"), timeout=timedelta(seconds=7))):
        assert psqlpy.pools[0].kwargs["connect_timeout_sec"] == 7
