"""tests/unit/e_infra/providers/drivers/auth/postgres: accounts and grants kept, revoked, found by digest — over a pool
that holds no database, its rows scripted by the statement that asks for them."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from e_infra.infra.auth.models import Account, Grant, GrantKind, Role
from e_infra.infra.errors import DatabaseError, ProviderError
from e_infra.ports.auth import AuthPort
from e_infra.providers.drivers.auth.postgres import PostgresAuthDriver

if TYPE_CHECKING:
    from e_infra.providers.drivers.database.psqlpy import PsqlpyDriver
    from support.psqlpy import FakePsqlpyServer
    from unit.e_infra.conftest import Logs

ANA = Account(owner="o-ana", name="ana", role=Role.USER)
NOW = datetime(2026, 10, 29, tzinfo=UTC)
ROW = {"id": "o-ana", "name": "ana", "role": "user", "created": NOW}
HELD = {**ROW, "digest": "d1", "kind": "key", "issued": NOW, "expires": NOW, "revoked": None}


async def test_postgres_meets_the_port(store: PostgresAuthDriver) -> None:
    assert isinstance(store, AuthPort)


async def test_postgres_open_creates_the_tables(
    psqlpy: FakePsqlpyServer, store: PostgresAuthDriver, logs: Logs
) -> None:
    _ = store
    assert [sql.split("(")[0].strip() for sql in psqlpy.sql()] == [
        "CREATE TABLE IF NOT EXISTS auth_account",
        "CREATE TABLE IF NOT EXISTS auth_grant",
        "CREATE INDEX IF NOT EXISTS auth_grant_owner ON auth_grant",
    ]


async def test_postgres_lifecycle_is_logged(database: PsqlpyDriver, logs: Logs) -> None:
    async with PostgresAuthDriver(database):
        pass
    assert logs.at("info", "auth postgres") == ["auth postgres opened", "auth postgres closed"]


async def test_postgres_health_follows_the_database(
    store: PostgresAuthDriver, psqlpy: FakePsqlpyServer, broken: Exception, logs: Logs
) -> None:
    assert await store.health() is True
    psqlpy.failures["SELECT 1"] = broken
    with pytest.raises(ProviderError):
        await store.health()
    assert logs.at("warning", "auth postgres") == ["auth postgres unhealthy"]


async def test_postgres_enroll_answers_the_stored_account(store: PostgresAuthDriver, psqlpy: FakePsqlpyServer) -> None:
    psqlpy.answers["INSERT INTO auth_account"] = [{**ROW, "name": "Ana"}]
    renamed = await store.enroll(ANA)
    assert (renamed.owner, renamed.name, renamed.created, psqlpy.statements[-1][1]) == (
        "o-ana",
        "Ana",
        NOW,
        ["o-ana", "ana", "user"],
    )


async def test_postgres_enroll_without_a_row_answers_the_account(store: PostgresAuthDriver) -> None:
    assert await store.enroll(ANA) == ANA


async def test_postgres_accounts(store: PostgresAuthDriver, psqlpy: FakePsqlpyServer) -> None:
    psqlpy.answers["ORDER BY created"] = [ROW]
    assert [(each.owner, each.role) for each in await store.accounts()] == [("o-ana", Role.USER)]


async def test_postgres_issue_binds_the_grant(store: PostgresAuthDriver, psqlpy: FakePsqlpyServer) -> None:
    await store.issue(Grant(digest="d1", owner="o-ana", created=NOW, expires=NOW))
    assert psqlpy.statements[-1][1] == ["d1", "o-ana", "key", NOW, NOW]


async def test_postgres_revoke_counts_what_the_database_stamped(
    store: PostgresAuthDriver, psqlpy: FakePsqlpyServer
) -> None:
    psqlpy.answers["UPDATE auth_grant"] = [{"digest": "d1"}, {"digest": "d2"}]
    assert (await store.revoke("o-ana"), psqlpy.statements[-1][1]) == (2, ["o-ana"])


async def test_postgres_holder_pairs_the_account_with_its_grant(
    store: PostgresAuthDriver, psqlpy: FakePsqlpyServer
) -> None:
    psqlpy.answers["JOIN auth_account"] = [HELD]
    held = await store.holder("d1")
    assert held is not None
    account, grant = held
    assert (account.owner, grant.digest, grant.kind, grant.expires, grant.revoked) == (
        "o-ana",
        "d1",
        GrantKind.KEY,
        NOW,
        None,
    )


async def test_postgres_holder_unknown_digest(store: PostgresAuthDriver) -> None:
    assert await store.holder("dx") is None


async def test_postgres_database_failure_is_a_database_error(
    store: PostgresAuthDriver, psqlpy: FakePsqlpyServer, broken: Exception
) -> None:
    psqlpy.failures["auth_account"] = broken
    with pytest.raises(DatabaseError, match="reset"):
        await store.accounts()
