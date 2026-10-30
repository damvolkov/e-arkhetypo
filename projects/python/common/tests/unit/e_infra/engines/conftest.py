"""tests/unit/e_infra/engines: dispatch over every durable queue — memory always, awa and PgQueuer each on this worker's
database of its own — and the providers the health survey asks.

`durable` is either durable queue, unentered; `background` is the engine over the queue a test is parametrized with,
unentered, with one queue of the test's own (two slots) and every write of a snapshot unthrottled; `warnings` records
what the engine warns, in place of its logger. `StubProvider` answers its health after `delay` seconds."""

import asyncio
from typing import TYPE_CHECKING, ClassVar, Self

import pytest

from e_infra.engines.dispatch import DispatchEngine
from e_infra.infra.background import Background
from e_infra.infra.config.base import Secret
from e_infra.ports.provider import Isolation, Locality, ProviderSpec, Workload
from e_infra.providers.drivers.queue.awa import AwaDriver
from e_infra.providers.drivers.queue.pgqueuer import PgqueuerDriver
from unit.e_infra.conftest import Warnings, Works

if TYPE_CHECKING:
    from e_infra.infra.config.queue import QueueSettings


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


def engine(request: pytest.FixtureRequest, name: str) -> AwaDriver | PgqueuerDriver:
    """The durable queue `name` on this worker's database of its own, not yet entered."""
    settings: QueueSettings = request.getfixturevalue("queue_settings")
    match name:
        case "awa":
            return AwaDriver(settings)
        case _:
            dsn = Secret(request.getfixturevalue("pgqueuer_database"))
            return PgqueuerDriver(settings.model_copy(update={"dsn": dsn}))


def build(durable: AwaDriver | PgqueuerDriver | None, queue: str, works: Works) -> DispatchEngine:
    """The engine over `durable` (memory alone when None), every scripted work registered on `queue`."""
    dispatch = DispatchEngine(durable, Background(), {queue: 2}, throttle=0)
    _ = [
        dispatch.register(kind, work, queue=queue)
        for kind, work in {"ok": works.ok, "boom": works.boom, "flaky": works.flaky, "hang": works.hang}.items()
    ]
    return dispatch


@pytest.fixture(params=[pytest.param("awa", marks=pytest.mark.db), pytest.param("pgqueuer", marks=pytest.mark.db)])
def durable(request: pytest.FixtureRequest) -> AwaDriver | PgqueuerDriver:
    return engine(request, request.param)


@pytest.fixture(
    params=["memory", pytest.param("awa", marks=pytest.mark.db), pytest.param("pgqueuer", marks=pytest.mark.db)]
)
def background(request: pytest.FixtureRequest, queue: str, works: Works) -> DispatchEngine:
    """The engine, not yet entered: its task group lives and dies in the test's own task."""
    match request.param:
        case "memory":
            return build(None, queue, works)
        case name:
            return build(engine(request, name), queue, works)
