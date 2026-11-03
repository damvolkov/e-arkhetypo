"""tests/unit/e_infra: the queue's test Postgres, shared by the background, dispatch and driver tests.

`queue_database` is this worker's own database beside POSTGRES_TEST_DSN's (default the stack's ParadeDB :45011),
created on the server's maintenance database when missing; with no server answering, every test that needs it skips
and says why — the memory engine's tests run regardless. `pgqueuer_database` is PgQueuer's, apart from awa's, so their
tables never meet. `queue_settings` is the queue at test pace, `queue` a queue name no other test shares. `settled`
reads a job until it settles, `running` until a worker runs it, `outage` takes a database down for a block: plain
helpers, imported by the tests (`pythonpath` holds tests/unit)."""

import os
import sys
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from itertools import count
from typing import TYPE_CHECKING, Any, Final, Protocol

import anyio
import pytest
import pytest_asyncio
from psqlpy import ConnectionPool
from psqlpy.exceptions import Error as PsqlError

from e_infra.infra.background import SETTLED, BackgroundState
from e_infra.infra.config.base import Secret
from e_infra.infra.config.providers.drivers.database.asyncpg import AsyncpgSettings
from e_infra.infra.config.providers.drivers.queue.awa import AwaSettings
from e_infra.infra.config.providers.drivers.queue.pgqueuer import PgqueuerSettings
from e_infra.providers.drivers.database.asyncpg import AsyncpgDriver

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, AsyncIterator, Callable, Mapping

    from e_infra.infra.background import BackgroundJob, BackgroundReporter

DSN: Final[str] = os.environ.get("POSTGRES_TEST_DSN", "postgresql://postgres:postgres@127.0.0.1:45011/e_infra_test")


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


async def busy(job: BackgroundJob) -> bool:
    """Whether the job is running; a pause before the next read when it is not."""
    _ = job.state is BackgroundState.RUNNING or await anyio.sleep(0.05)
    return job.state is BackgroundState.RUNNING


async def running(reader: Reader, job: str, seconds: float = 10) -> BackgroundJob:
    """The job once a worker runs it, read every 50 ms; the test fails after `seconds`."""
    with anyio.fail_after(seconds):
        return await anext(found for _ in count() if (found := await reader.job(job)) and await busy(found))


async def settled(reader: Reader, job: str, seconds: float = 10) -> BackgroundJob:
    """The job once settled, read every 50 ms; the test fails after `seconds`."""
    with anyio.fail_after(seconds):
        return await anext(found for _ in count() if (found := await reader.job(job)) and await done(found))


async def idle() -> bool:
    """A pause of 50 ms that answers False: the not-yet of a poll."""
    await anyio.sleep(0.05)
    return False


async def until(ready: Callable[[], bool], seconds: float = 10) -> None:
    """Returns once `ready()` holds, checked every 50 ms; the test fails after `seconds`."""
    with anyio.fail_after(seconds):
        await anext(None for _ in count() if ready() or await idle())


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


class Works:
    """Scripted works: `ok` reports twice, `boom` raises, `flaky` raises on its first attempt only, `hang` reports
    once then waits until cancelled — `started` and `interrupted` mark it."""

    def __init__(self) -> None:
        self.started = anyio.Event()
        self.interrupted = anyio.Event()
        self.calls: list[Mapping[str, Any]] = []

    async def ok(self, args: Mapping[str, Any], report: BackgroundReporter) -> None:
        self.calls.append(args)
        await report({"stage": "fetch", "seen": 1})
        await report({"stage": "smoke", "seen": 2})

    async def boom(self, _args: Mapping[str, Any], _report: BackgroundReporter) -> None:
        msg = "bad"
        raise ValueError(msg)

    async def flaky(self, args: Mapping[str, Any], report: BackgroundReporter) -> None:
        self.calls.append(args)
        _ = len(self.calls) == 1 and await self.boom(args, report)
        await report({"stage": "smoke"})

    async def hang(self, _args: Mapping[str, Any], report: BackgroundReporter) -> None:
        await report({"stage": "discover"})
        self.started.set()
        try:
            await anyio.sleep_forever()
        finally:
            self.interrupted.set()


class Warnings:
    """A logger that keeps the events it is warned of; every other level is said, not kept."""

    def __init__(self) -> None:
        self.events: list[str] = []

    def warning(self, event: str, **_: object) -> None:
        self.events.append(event)

    def debug(self, event: str, **_: object) -> None:
        """Said, not kept: only warnings are asserted."""

    info = error = debug


class Logs:
    """A logger that keeps everything it is told: level, event, fields — what a test asserts a driver logged."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, object]]] = []

    def debug(self, event: str, **fields: object) -> None:
        self.events.append(("debug", event, fields))

    def info(self, event: str, **fields: object) -> None:
        self.events.append(("info", event, fields))

    def warning(self, event: str, **fields: object) -> None:
        self.events.append(("warning", event, fields))

    def error(self, event: str, **fields: object) -> None:
        self.events.append(("error", event, fields))

    def at(self, level: str, prefix: str = "") -> list[str]:
        """The events told at one level, in order — those of one provider when its name is the `prefix`."""
        return [event for told, event, _ in self.events if told == level and event.startswith(prefix)]


@pytest.fixture
def logs(monkeypatch: pytest.MonkeyPatch) -> Logs:
    """Every `logger` of the package replaced by one recorder, for the test's length."""
    recorder = Logs()
    _ = [
        monkeypatch.setattr(module, "logger", recorder)
        for name, module in tuple(sys.modules.items())
        if name.startswith("e_infra.") and name != "e_infra.infra.logger" and hasattr(module, "logger")
    ]
    return recorder


@pytest.fixture
def works() -> Works:
    return Works()


REACHED: Final[dict[str, str]] = {}


async def reachable(name: str) -> str:
    """The DSN of the test database `name` beside POSTGRES_TEST_DSN's, created when missing — or the test skips and says
    why. Asked for only by what needs a server: the memory engine's tests never reach here."""
    try:
        REACHED.setdefault(name, await create(f"{DSN}_{name}"))
    except PsqlError as error:
        pytest.skip(f"no test Postgres at {DSN.rpartition('@')[2]}: {error}")
    return REACHED[name]


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def queue_database(worker_id: str) -> str:
    """This worker's queue database, as in production a database of its own."""
    return await reachable(f"queue_{worker_id}")


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def pgqueuer_database(worker_id: str) -> str:
    """This worker's PgQueuer database: its tables and the adapter's own never meet awa's."""
    return await reachable(f"pgqueuer_{worker_id}")


PACE: Final[dict[str, Any]] = {
    "poll": timedelta(milliseconds=50),
    "drain": timedelta(seconds=1),
    "timeout": timedelta(seconds=5),
}


@pytest.fixture
def queue_settings(queue_database: str) -> AwaSettings:
    """The awa queue at test pace: a short poll and drain, calls that give up within five seconds."""
    return AwaSettings(dsn=Secret(queue_database), pool=8, **PACE)


@pytest.fixture
def pgqueuer_settings() -> PgqueuerSettings:
    """PgQueuer at test pace: a short poll, drain and restart, calls that give up within five seconds."""
    return PgqueuerSettings(restart=timedelta(milliseconds=50), **PACE)


@pytest.fixture
async def pgqueuer_db(pgqueuer_database: str) -> AsyncIterator[AsyncpgDriver]:
    """The asyncpg driver PgQueuer rides, open on this worker's database."""
    async with AsyncpgDriver(
        AsyncpgSettings(dsn=Secret(pgqueuer_database), pool=4, timeout=timedelta(seconds=5))
    ) as db:
        yield db


@dataclass(frozen=True, slots=True)
class Queues:
    """Both durable queues at test pace, their databases reached only when asked: a test that runs the memory engine
    holds a `Queues` and touches no server."""

    worker: str
    pgqueuer: PgqueuerSettings

    async def awa(self) -> AwaSettings:
        return AwaSettings(dsn=Secret(await reachable(f"queue_{self.worker}")), pool=8, **PACE)

    async def database(self) -> str:
        return await reachable(f"pgqueuer_{self.worker}")


@pytest.fixture
def queues(worker_id: str, pgqueuer_settings: PgqueuerSettings) -> Queues:
    return Queues(worker_id, pgqueuer_settings)


@pytest.fixture
def queue() -> str:
    """A queue name of this test's own: jobs of other tests and earlier runs never reach its workers."""
    return f"q{uuid.uuid4().hex[:12]}"
