"""tests/unit/e_infra/infra: background over every engine — memory always, awa and PgQueuer each on this worker's
database of its own.

`durable` is either durable engine, unconnected; `background` is the facade over the engine a test is parametrized
with, unentered, with one queue of the test's own (two slots) and every write of a snapshot unthrottled; `works` are
the scripted works it runs, by kind. `warnings` records what the module warns, in place of its logger."""

from typing import TYPE_CHECKING, Any

import anyio
import pytest

from e_infra.adapters.awa import AwaAdapter
from e_infra.adapters.pgqueuer import PgqueuerAdapter
from e_infra.infra.background import Background
from e_infra.infra.config.base import Secret

if TYPE_CHECKING:
    from collections.abc import Mapping

    from e_infra.infra.background import BackgroundReporter
    from e_infra.infra.config.queue import QueueSettings


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
    """A logger that keeps the events it is warned of."""

    def __init__(self) -> None:
        self.events: list[str] = []

    def warning(self, event: str, **_: object) -> None:
        self.events.append(event)


@pytest.fixture
def works() -> Works:
    return Works()


@pytest.fixture
def warnings(monkeypatch: pytest.MonkeyPatch) -> Warnings:
    recorder = Warnings()
    monkeypatch.setattr("e_infra.infra.background.logger", recorder)
    return recorder


def engine(request: pytest.FixtureRequest, name: str) -> AwaAdapter | PgqueuerAdapter:
    """The durable engine `name` on this worker's database of its own, not yet connected."""
    settings: QueueSettings = request.getfixturevalue("queue_settings")
    match name:
        case "awa":
            return AwaAdapter(settings)
        case _:
            dsn = Secret(request.getfixturevalue("pgqueuer_database"))
            return PgqueuerAdapter(settings.model_copy(update={"dsn": dsn}))


def build(durable: AwaAdapter | PgqueuerAdapter | None, queue: str, works: Works) -> Background:
    """The facade over `durable` (memory alone when None), every scripted work registered on `queue`."""
    background = Background(durable, {queue: 2}, throttle=0)
    _ = [
        background.register(kind, work, queue=queue)
        for kind, work in {"ok": works.ok, "boom": works.boom, "flaky": works.flaky, "hang": works.hang}.items()
    ]
    return background


@pytest.fixture(params=[pytest.param("awa", marks=pytest.mark.db), pytest.param("pgqueuer", marks=pytest.mark.db)])
def durable(request: pytest.FixtureRequest) -> AwaAdapter | PgqueuerAdapter:
    return engine(request, request.param)


@pytest.fixture(
    params=["memory", pytest.param("awa", marks=pytest.mark.db), pytest.param("pgqueuer", marks=pytest.mark.db)]
)
def background(request: pytest.FixtureRequest, queue: str, works: Works) -> Background:
    """The facade, not yet entered: its task group lives and dies in the test's own task."""
    match request.param:
        case "memory":
            return build(None, queue, works)
        case name:
            return build(engine(request, name), queue, works)
