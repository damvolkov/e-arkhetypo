"""tests/unit/e_core: the queue's test Postgres, shared by the background and adapter tests.

`queue_database` is this worker's own database beside POSTGRES_TEST_DSN's (default the stack's ParadeDB :45011),
created on the server's maintenance database when missing; with no server answering, every test that needs it skips
and says why — the memory engine's tests run regardless. `queue_settings` is the queue at test pace, `queue` a queue
name no other test shares. `settled` reads a job until it settles, `outage` takes a database down for a block: plain
helpers, imported by the tests (`pythonpath` holds tests/unit)."""

import os
import uuid
from contextlib import asynccontextmanager
from datetime import timedelta
from itertools import count
from typing import TYPE_CHECKING, Final, Protocol

import anyio
import pytest
import pytest_asyncio
from psqlpy import ConnectionPool
from psqlpy.exceptions import Error as PsqlError

from e_core.core.background import SETTLED
from e_core.core.settings.base import Secret
from e_core.core.settings.queue import QueueSettings

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from e_core.core.background import BackgroundJob

DSN: Final[str] = os.environ.get("POSTGRES_TEST_DSN", "postgresql://postgres:postgres@127.0.0.1:45011/e_core_test")


class Reader(Protocol):
    """Whatever reads a job by id: an engine, or the facade."""

    async def job(self, job: str) -> BackgroundJob | None: ...


async def admin(dsn: str, *statements: tuple[str, list[object]]) -> None:
    """Run statements on the server's maintenance database, outside any transaction: CREATE and ALTER DATABASE need it."""
    head, _, _ = dsn.rpartition("/")
    pool = ConnectionPool(dsn=f"{head}/postgres", max_db_pool_size=2, connect_timeout_sec=2)
    try:
        async with pool.acquire() as connection:
            _ = [await connection.execute(query, params) for query, params in statements]
    finally:
        pool.close()


async def create(dsn: str) -> str:
    """The DSN back, its database created when missing."""
    head, _, name = dsn.rpartition("/")
    pool = ConnectionPool(dsn=f"{head}/postgres", max_db_pool_size=2, connect_timeout_sec=2)
    try:
        async with pool.acquire() as connection:
            found = (await connection.fetch("SELECT 1 FROM pg_database WHERE datname = $1", [name])).result()
            ### CREATE DATABASE takes no parameters; the name is this module's constant and xdist's worker id.
            _ = found or await connection.execute(f'CREATE DATABASE "{name}"')
    finally:
        pool.close()
    return dsn


async def done(job: BackgroundJob) -> bool:
    """Whether the job settled; a pause before the next read when it has not."""
    _ = job.state in SETTLED or await anyio.sleep(0.05)
    return job.state in SETTLED


async def settled(reader: Reader, job: str, seconds: float = 10) -> BackgroundJob:
    """The job once settled, read every 50 ms; the test fails after `seconds`."""
    with anyio.fail_after(seconds):
        return await anext(found for _ in count() if (found := await reader.job(job)) and await done(found))


@asynccontextmanager
async def outage(dsn: str) -> AsyncGenerator[None]:
    """The database down for the block: no new connection admitted, every open one terminated; back up after."""
    name = dsn.rpartition("/")[2]
    ### ALTER DATABASE takes no parameters; the name is a test database's, built from this module's constant.
    await admin(
        dsn,
        (f'ALTER DATABASE "{name}" WITH ALLOW_CONNECTIONS false', []),
        ("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = $1", [name]),
    )
    try:
        yield
    finally:
        await admin(dsn, (f'ALTER DATABASE "{name}" WITH ALLOW_CONNECTIONS true', []))


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def queue_database(worker_id: str) -> str:
    """This worker's queue database, as in production a database of its own."""
    try:
        return await create(f"{DSN}_queue_{worker_id}")
    except PsqlError as error:
        pytest.skip(f"no test Postgres at {DSN.rpartition('@')[2]}: {error}")


@pytest.fixture
def queue_settings(queue_database: str) -> QueueSettings:
    """The queue at test pace: a short poll and drain, calls that give up within five seconds."""
    return QueueSettings(
        dsn=Secret(queue_database),
        pool=8,
        poll=timedelta(milliseconds=50),
        drain=timedelta(seconds=1),
        timeout=timedelta(seconds=5),
    )


@pytest.fixture
def queue() -> str:
    """A queue name of this test's own: jobs of other tests and earlier runs never reach its workers."""
    return f"q{uuid.uuid4().hex[:12]}"
