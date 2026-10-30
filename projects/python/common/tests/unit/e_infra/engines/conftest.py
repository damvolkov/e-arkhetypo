"""tests/unit/e_infra/engines: dispatch over every durable queue — memory always, awa and PgQueuer each on this worker's
database of its own — and the providers the health survey asks.

`durable` is either durable queue, unentered; `background` is the engine over the queue a test is parametrized with,
unentered, with one queue of the test's own (two slots) and every write of a snapshot unthrottled; `warnings` records
what the engine warns, in place of its logger. `StubProvider` answers its health after `delay` seconds."""

import asyncio
from contextlib import AsyncExitStack
from datetime import timedelta
from typing import TYPE_CHECKING, ClassVar, Self

import pytest

from e_infra.engines.dispatch import DispatchEngine
from e_infra.infra.background import Background
from e_infra.infra.config.base import Secret
from e_infra.infra.config.providers.drivers.database.asyncpg import AsyncpgSettings
from e_infra.ports.provider import Isolation, Locality, ProviderSpec, Workload
from e_infra.providers.drivers.database.asyncpg import AsyncpgDriver
from e_infra.providers.drivers.queue.awa import AwaDriver
from e_infra.providers.drivers.queue.pgqueuer import PgqueuerDriver
from unit.e_infra.conftest import Queues, Warnings, Works

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


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
            return AwaDriver(queues.awa)
        case _:
            db = AsyncpgDriver(AsyncpgSettings(dsn=Secret(queues.database), pool=4, timeout=timedelta(seconds=5)))
            return PgqueuerDriver(await stack.enter_async_context(db), queues.pgqueuer)


def build(durable: AwaDriver | PgqueuerDriver | None, queue: str, works: Works) -> DispatchEngine:
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
