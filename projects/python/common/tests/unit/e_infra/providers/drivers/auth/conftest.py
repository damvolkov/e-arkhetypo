"""tests/unit/e_infra/providers/drivers/auth: the auth driver over a psqlpy pool that holds no database.

`psqlpy` is the scripted server (rows answered by a fragment of the statement, every statement recorded) the psqlpy
driver is patched to build its pool from; `scripted` is a `PsqlpyDriver` over it, `store` a `PostgresAuthDriver` open on that."""

from typing import TYPE_CHECKING

import pytest
from psqlpy.exceptions import Error as PsqlError

from e_infra.providers.drivers.auth.postgres import PostgresAuthDriver
from e_infra.providers.drivers.database import psqlpy as psqlpy_module
from e_infra.providers.drivers.database.psqlpy import PsqlpyDriver
from support.psqlpy import FakePsqlpyServer
from unit.e_infra.conftest import psqlpy_args

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@pytest.fixture
def psqlpy(monkeypatch: pytest.MonkeyPatch) -> FakePsqlpyServer:
    server = FakePsqlpyServer()
    monkeypatch.setattr(psqlpy_module, "ConnectionPool", server.pool)
    return server


@pytest.fixture
async def scripted(psqlpy: FakePsqlpyServer) -> AsyncIterator[PsqlpyDriver]:
    _ = psqlpy
    async with PsqlpyDriver(**psqlpy_args(pool=2)) as opened:
        yield opened


@pytest.fixture
async def store(scripted: PsqlpyDriver) -> AsyncIterator[PostgresAuthDriver]:
    async with PostgresAuthDriver(scripted) as opened:
        yield opened


@pytest.fixture
def broken() -> PsqlError:
    """The library's own error, as a connection that reset raises it."""
    return PsqlError("connection reset")
