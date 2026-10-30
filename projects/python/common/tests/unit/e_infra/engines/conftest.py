"""tests/unit/e_infra/engines: dispatch over every durable queue — memory always, awa and PgQueuer each on this worker's
database of its own — and the providers the health survey asks.

`durable` is either durable queue, unentered; `background` is the engine over the queue a test is parametrized with,
unentered, with one queue of the test's own (two slots) and every write of a snapshot unthrottled; `warnings` records
what the engine warns, in place of its logger. `StubProvider` answers its health after `delay` seconds."""

import asyncio
from contextlib import AsyncExitStack
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, ClassVar, Self

import pytest

from e_infra.engines.dispatch import DispatchEngine
from e_infra.infra.background import Background, BackgroundJob, BackgroundState
from e_infra.infra.config.base import Secret
from e_infra.infra.config.providers.drivers.database.asyncpg import AsyncpgSettings
from e_infra.infra.errors import QueueError
from e_infra.ports.provider import Isolation, Locality, ProviderSpec, Workload
from e_infra.providers.drivers.database.asyncpg import AsyncpgDriver
from e_infra.providers.drivers.queue.awa import AwaDriver
from e_infra.providers.drivers.queue.pgqueuer import PgqueuerDriver
from unit.e_infra.conftest import Queues, Warnings, Works

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping

    from e_infra.infra.background import BackgroundFire, BackgroundHandler
    from e_infra.ports.queue import QueuePort


##### HEALTH #####
class StubProvider:
    """A provider that answers its health after `delay` seconds — `up` or not — or breaks its contract with `error`."""

    spec: ClassVar[ProviderSpec] = ProviderSpec("stub", Locality.EMBEDDED, Workload.CPU_BOUND, Isolation.LOOP)

    def __init__(self, delay: float = 0.0, *, up: bool = True, error: BaseException | None = None) -> None:
        self.delay, self.up, self.error = delay, up, error

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Nothing to release."""

    async def health(self) -> bool:
        await asyncio.sleep(self.delay)
        match self.error:
            case None:
                return self.up
            case error:
                raise error


##### A DURABLE QUEUE THAT HOLDS NOTHING #####
class FakeQueue:
    """A `QueuePort` and `SchedulePort` that keeps its jobs in a dict: `unreachable` fails its entry, `down` every call
    after — as a database that went away — with the port's own `QueueError`."""

    spec: ClassVar[ProviderSpec] = ProviderSpec("fake-queue", Locality.EMBEDDED, Workload.IO_BOUND, Isolation.LOOP)

    def __init__(self, *, unreachable: bool = False) -> None:
        self.unreachable = unreachable
        self.down = False
        self.jobs_held: dict[str, BackgroundJob] = {}
        self.handlers: dict[str, tuple[str, BackgroundHandler]] = {}
        self.clock: dict[str, tuple[str, BackgroundFire]] = {}
        self.slots: Mapping[str, int] = {}

    def _check(self) -> None:
        if self.down:
            msg = "connection reset"
            raise QueueError(msg)

    async def __aenter__(self) -> Self:
        if self.unreachable:
            msg = "connection refused"
            raise QueueError(msg)
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Nothing to release."""

    async def health(self) -> bool:
        return not self.down

    def register(self, kind: str, queue: str, handler: BackgroundHandler) -> None:
        self.handlers[kind] = (queue, handler)

    def schedule(self, name: str, cron: str, fire: BackgroundFire) -> None:
        self.clock[name] = (cron, fire)

    async def start(self, slots: Mapping[str, int]) -> None:
        self.slots = slots

    async def enqueue(self, kind: str, args: Mapping[str, Any], *, queue: str, attempts: int) -> BackgroundJob:
        self._check()
        job = BackgroundJob(
            id=str(len(self.jobs_held) + 1),
            kind=kind,
            queue=queue,
            state=BackgroundState.AVAILABLE,
            attempt=0,
            args=args,
            created=datetime.now(UTC),
        )
        self.jobs_held[job.id] = job
        return job

    async def job(self, job: str) -> BackgroundJob | None:
        self._check()
        return self.jobs_held.get(job)

    async def jobs(
        self, *, kind: str | None = None, state: BackgroundState | None = None, limit: int = 20
    ) -> list[BackgroundJob]:
        self._check()
        held = [j for j in self.jobs_held.values() if kind in (None, j.kind) and state in (None, j.state)]
        return held[:limit]

    async def cancel(self, job: str) -> BackgroundJob | None:
        self._check()
        return self.jobs_held.get(job)


##### DISPATCH #####
@pytest.fixture
def warnings(monkeypatch: pytest.MonkeyPatch) -> Warnings:
    recorder = Warnings()
    monkeypatch.setattr("e_infra.engines.dispatch.logger", recorder)
    return recorder


async def engine(name: str, stack: AsyncExitStack, queues: Queues) -> AwaDriver | PgqueuerDriver:
    """The durable queue `name` on this worker's database of its own, not yet entered; PgQueuer's asyncpg driver is
    entered on `stack`, as the lifespan would before it."""
    match name:
        case "awa":
            return AwaDriver(await queues.awa())
        case _:
            db = AsyncpgDriver(
                AsyncpgSettings(dsn=Secret(await queues.database()), pool=4, timeout=timedelta(seconds=5))
            )
            return PgqueuerDriver(await stack.enter_async_context(db), queues.pgqueuer)


def build(durable: QueuePort | None, queue: str, works: Works) -> DispatchEngine:
    """The engine over `durable` (memory alone when None), every scripted work registered on `queue`."""
    dispatch = DispatchEngine(durable, Background(), {queue: 2}, throttle=0)
    _ = [
        dispatch.register(kind, work, queue=queue)
        for kind, work in {"ok": works.ok, "boom": works.boom, "flaky": works.flaky, "hang": works.hang}.items()
    ]
    return dispatch


@pytest.fixture(
    params=[pytest.param("awa", marks=pytest.mark.integration), pytest.param("pgqueuer", marks=pytest.mark.integration)]
)
async def durable(request: pytest.FixtureRequest, queues: Queues) -> AsyncIterator[AwaDriver | PgqueuerDriver]:
    async with AsyncExitStack() as stack:
        yield await engine(request.param, stack, queues)


@pytest.fixture(
    params=[
        "memory",
        pytest.param("awa", marks=pytest.mark.integration),
        pytest.param("pgqueuer", marks=pytest.mark.integration),
    ]
)
async def background(
    request: pytest.FixtureRequest, queue: str, works: Works, queues: Queues
) -> AsyncIterator[DispatchEngine]:
    """The engine, not yet entered: its task group lives and dies in the test's own task."""
    async with AsyncExitStack() as stack:
        match request.param:
            case "memory":
                yield build(None, queue, works)
            case name:
                yield build(await engine(name, stack, queues), queue, works)
