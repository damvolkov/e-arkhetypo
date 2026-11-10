"""tests/unit/e_infra/providers/drivers/auth/postgres_real: the auth tables created by many instances opening at once."""

import asyncio
from typing import TYPE_CHECKING

import pytest

from e_infra.providers.drivers.auth.postgres import PostgresAuthDriver
from support.query import sql

if TYPE_CHECKING:
    from e_infra.providers.drivers.database.psqlpy import PsqlpyDriver

pytestmark = pytest.mark.integration


async def test_postgres_opened_at_once_makes_the_tables_once(fleet: list[PsqlpyDriver]) -> None:
    """`CREATE TABLE IF NOT EXISTS` alone is not safe under concurrency: two creators collide on `pg_type`."""
    await fleet[0].execute(sql("DROP TABLE IF EXISTS auth_grant"))
    await fleet[0].execute(sql("DROP TABLE IF EXISTS auth_account"))
    stores = [PostgresAuthDriver(db) for db in fleet]
    await asyncio.gather(*(store.__aenter__() for store in stores))
    assert await fleet[0].row(sql("SELECT count(*) AS n FROM pg_tables WHERE tablename LIKE 'auth_%'")) == {"n": 2}
