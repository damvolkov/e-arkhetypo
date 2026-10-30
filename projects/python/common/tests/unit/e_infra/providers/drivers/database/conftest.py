"""tests/unit/e_infra/providers/drivers/database: the psqlpy pool that holds no database.

`psqlpy` is the fake server (scripted rows, recorded SQL) the driver is patched to build its pool from; `driver` is a
`PsqlpyDriver` over it, not yet open; `broken` is the library's own error, as a connection that reset raises it."""

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from psqlpy.exceptions import Error as PsqlError

from e_infra.infra.config.base import Secret
from e_infra.infra.config.providers.drivers.database.asyncpg import AsyncpgSettings
from e_infra.infra.config.providers.drivers.database.psqlpy import PsqlpySettings
from e_infra.providers.drivers.database import psqlpy as psqlpy_module
from e_infra.providers.drivers.database.asyncpg import AsyncpgDriver
from e_infra.providers.drivers.database.psqlpy import PsqlpyDriver
from support.psqlpy import FakePsqlpyServer

if TYPE_CHECKING:
    from support.asyncpg import FakeAsyncpgServer

ASYNCPG_DSN = "postgresql://u:p@db:5432/x"


@pytest.fixture
def psqlpy(monkeypatch: pytest.MonkeyPatch) -> FakePsqlpyServer:
    server = FakePsqlpyServer()
    monkeypatch.setattr(psqlpy_module, "ConnectionPool", server.pool)
    return server


@pytest.fixture
def driver(psqlpy: FakePsqlpyServer) -> PsqlpyDriver:
    return PsqlpyDriver(PsqlpySettings(dsn=Secret("postgresql://u:p@db:5432/x"), pool=4))


@pytest.fixture
def broken() -> PsqlError:
    return PsqlError("connection reset")


@pytest.fixture
def asyncpg_driver(asyncpg_server: FakeAsyncpgServer) -> AsyncpgDriver:
    """An `AsyncpgDriver` over the fake server, not yet open."""
    return AsyncpgDriver(AsyncpgSettings(dsn=Secret(ASYNCPG_DSN), pool_min=2, pool=4, timeout=timedelta(seconds=3)))
