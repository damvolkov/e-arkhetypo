"""tests/unit/e_infra/providers/drivers/queue: the real queues — awa and PgQueuer on the test Postgres — and their scripted handlers.

`port` is either durable queue, unentered, for the contract both hold; `Flaky` and `Hang` are scripted handlers;
`refuse` makes the queue's database turn new connections away; `stuck` makes awa's shutdown never return."""

from dataclasses import dataclass
from datetime import timedelta
from functools import partial
from typing import TYPE_CHECKING

import anyio
import pytest
from awa import AsyncClient

from e_infra.infra.config.base import Secret
from e_infra.infra.config.providers.drivers.database.asyncpg import AsyncpgSettings
from e_infra.infra.config.providers.drivers.queue.awa import AwaSettings
from e_infra.providers.drivers.database.asyncpg import AsyncpgDriver
from e_infra.providers.drivers.queue import awa as awa_module
from e_infra.providers.drivers.queue import pgqueuer as pgqueuer_module
from e_infra.providers.drivers.queue.awa import AwaDriver
from e_infra.providers.drivers.queue.pgqueuer import PgqueuerDriver
from support.awa import FakeAwaClient
from support.pgqueuer import FakePgqueuer
from unit.e_infra.conftest import admin

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from e_infra.infra.background import BackgroundHandler, BackgroundRun
    from e_infra.infra.config.providers.drivers.queue.pgqueuer import PgqueuerSettings
    from support.asyncpg import FakeAsyncpgServer


@pytest.fixture
async def awa(queue_settings: AwaSettings) -> AsyncIterator[AwaDriver]:
    async with AwaDriver(queue_settings) as adapter:
        yield adapter


@pytest.fixture
async def refuse(queue_database: str) -> AsyncIterator[Callable[[], Awaitable[None]]]:
    """Make the queue's database refuse every new connection — those already open stay — as a server out of slots
    does; it accepts them again once the test is over."""
    name = queue_database.rpartition("/")[2]

    async def allow(flag: bool) -> None:
        ### ALTER DATABASE takes no parameters; the name is this worker's queue database.
        await admin(queue_database, (f'ALTER DATABASE "{name}" ALLOW_CONNECTIONS {str(flag).lower()}', []))

    try:
        yield partial(allow, False)
    finally:
        await allow(True)


async def reported(run: BackgroundRun) -> None:
    await run.report({"done": True})


@pytest.fixture
def handler() -> BackgroundHandler:
    """A job's handler that reports once and returns."""
    return reported


@pytest.fixture
def stuck(monkeypatch: pytest.MonkeyPatch) -> None:
    """An awa shutdown that never returns — after it has really stopped the runtime and closed the pool, so a test
    that lets the client go leaks no connection."""
    shutdown, close = AsyncClient.shutdown, AsyncClient.close

    async def never(client: AsyncClient, timeout_ms: int = 2000) -> None:
        await shutdown(client, timeout_ms)
        await close(client)
        await anyio.sleep_forever()

    monkeypatch.setattr(AsyncClient, "shutdown", never)


##### ENGINES — the same contract on awa and on PgQueuer, each on a database of its own #####
@pytest.fixture(params=["awa", "pgqueuer"])
async def port(
    request: pytest.FixtureRequest,
    queue_settings: AwaSettings,
    pgqueuer_settings: PgqueuerSettings,
    pgqueuer_db: AsyncpgDriver,
) -> AwaDriver | PgqueuerDriver:
    """The durable engine under test, not yet connected (PgQueuer's asyncpg driver is open beneath it)."""
    return AwaDriver(queue_settings) if request.param == "awa" else PgqueuerDriver(pgqueuer_db, pgqueuer_settings)


@pytest.fixture
def engine(pgqueuer_db: AsyncpgDriver, pgqueuer_settings: PgqueuerSettings) -> PgqueuerDriver:
    """A PgQueuer engine on this worker's database, short timeouts, not yet connected."""
    return PgqueuerDriver(pgqueuer_db, pgqueuer_settings.model_copy(update={"timeout": timedelta(seconds=1)}))


@dataclass(slots=True)
class Flaky:
    """A handler that fails its first `fails` attempts, then reports and returns."""

    fails: int
    seen: int = 0

    async def __call__(self, run: BackgroundRun) -> None:
        self.seen += 1
        _ = self.seen <= self.fails and self._fail()
        await run.report({"attempt": self.seen})

    def _fail(self) -> None:
        msg = f"attempt {self.seen} failed"
        raise RuntimeError(msg)


@dataclass(slots=True)
class Hang:
    """A handler that reports, then waits forever; `cancelled` once its wait was interrupted."""

    cancelled: bool = False

    async def __call__(self, run: BackgroundRun) -> None:
        await run.report({"hanging": True})
        try:
            await anyio.sleep_forever()
        except anyio.get_cancelled_exc_class():
            self.cancelled = True
            raise


@pytest.fixture
def hang() -> Hang:
    return Hang()


@pytest.fixture
def flaky() -> Callable[[int], Flaky]:
    return Flaky


##### AWA — a client that holds no database #####
@pytest.fixture
def awa_script() -> dict[str, BaseException]:
    """What the clients fail at, by method: scripted before the driver opens, shared by every client it builds."""
    return {}


@pytest.fixture
def awa_clients(monkeypatch: pytest.MonkeyPatch, awa_script: dict[str, BaseException]) -> list[FakeAwaClient]:
    """Every client the driver builds while a test runs, in order: the driver is patched to build fakes."""
    built: list[FakeAwaClient] = []

    def client(dsn: str, max_connections: int = 10) -> FakeAwaClient:
        built.append(FakeAwaClient(dsn, max_connections))
        built[-1].failures = awa_script
        return built[-1]

    monkeypatch.setattr(awa_module, "AsyncClient", client)
    return built


@pytest.fixture
def awa_settings() -> AwaSettings:
    """awa at unit pace: the smallest legal pool, a short drain, calls that give up within a second."""
    return AwaSettings(
        pool=6, poll=timedelta(milliseconds=10), drain=timedelta(milliseconds=50), timeout=timedelta(seconds=1)
    )


@pytest.fixture
def awa_driver(awa_clients: list[FakeAwaClient], awa_settings: AwaSettings) -> AwaDriver:
    """The awa driver over the fake client, not yet open."""
    return AwaDriver(awa_settings)


##### PGQUEUER — PgQueuer's in-memory backend over a pool that holds no database #####
@pytest.fixture
def pgqueuer_memory(monkeypatch: pytest.MonkeyPatch) -> FakePgqueuer:
    """`Queries.from_asyncpg_connection` patched to answer PgQueuer's own in-memory backend."""
    memory = FakePgqueuer()
    monkeypatch.setattr(pgqueuer_module, "Queries", memory)
    return memory


@pytest.fixture
async def fake_db(asyncpg_server: FakeAsyncpgServer) -> AsyncIterator[AsyncpgDriver]:
    """The asyncpg driver PgQueuer rides, open over the fake server."""
    async with AsyncpgDriver(AsyncpgSettings(dsn=Secret("postgresql://u:p@db/q"), timeout=timedelta(seconds=1))) as db:
        yield db


@pytest.fixture
def pgqueuer_driver(
    fake_db: AsyncpgDriver, pgqueuer_memory: FakePgqueuer, pgqueuer_settings: PgqueuerSettings
) -> PgqueuerDriver:
    """The PgQueuer driver over the open fake driver and the in-memory backend, not yet open itself."""
    return PgqueuerDriver(fake_db, pgqueuer_settings)


@pytest.fixture
async def opened(pgqueuer_driver: PgqueuerDriver) -> PgqueuerDriver:
    """The PgQueuer driver, entered."""
    await pgqueuer_driver.__aenter__()
    return pgqueuer_driver


@pytest.fixture
async def awa_opened(awa_driver: AwaDriver) -> AwaDriver:
    """The awa driver, entered."""
    await awa_driver.__aenter__()
    return awa_driver
