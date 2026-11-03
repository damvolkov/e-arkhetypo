"""tests/unit/e_infra/providers/drivers/auth: the auth driver over a psqlpy pool that holds no database.

`psqlpy` is the scripted server (rows answered by a fragment of the statement, every statement recorded) the psqlpy
driver is patched to build its pool from; `store` is an `AuthPostgresDriver` open on a `PsqlpyDriver` over it."""

from typing import TYPE_CHECKING

import pytest
from psqlpy.exceptions import Error as PsqlError

from e_infra.infra.config.base import Secret
from e_infra.infra.config.providers.drivers.database.psqlpy import PsqlpySettings
from e_infra.providers.drivers.auth.postgres import AuthPostgresDriver
from e_infra.providers.drivers.database import psqlpy as psqlpy_module
from e_infra.providers.drivers.database.psqlpy import PsqlpyDriver
from support.psqlpy import FakePsqlpyServer

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@pytest.fixture
def psqlpy(monkeypatch: pytest.MonkeyPatch) -> FakePsqlpyServer:
    server = FakePsqlpyServer()
    monkeypatch.setattr(psqlpy_module, "ConnectionPool", server.pool)
    return server


@pytest.fixture
async def database(psqlpy: FakePsqlpyServer) -> AsyncIterator[PsqlpyDriver]:
    _ = psqlpy
    async with PsqlpyDriver(PsqlpySettings(dsn=Secret("postgresql://u:p@db:5432/x"), pool=2)) as opened:
        yield opened


@pytest.fixture
async def store(database: PsqlpyDriver) -> AsyncIterator[AuthPostgresDriver]:
    async with AuthPostgresDriver(database) as opened:
        yield opened


@pytest.fixture
def broken() -> PsqlError:
    """The library's own error, as a connection that reset raises it."""
    return PsqlError("connection reset")
