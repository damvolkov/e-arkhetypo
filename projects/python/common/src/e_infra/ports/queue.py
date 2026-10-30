"""ports/queue: a durable job queue — kinds bound to handlers on named queues, jobs enqueued, read and cancelled."""

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from e_infra.ports.provider import Provider

if TYPE_CHECKING:
    from collections.abc import Mapping

    from e_infra.infra.background import BackgroundFire, BackgroundHandler, BackgroundJob, BackgroundState


@runtime_checkable
class QueuePort(Provider, Protocol):
    """An engine: `register` binds a kind to its handler on a queue before `start` runs `slots` workers per queue; a
    handler that returns completes its job, one that raises retries it until `attempts` are spent. `job`, `jobs` and
    `cancel` read and settle what is held; an unknown id is None. An engine that cannot be reached raises `QueueError`."""

    def register(self, kind: str, queue: str, handler: BackgroundHandler) -> None: ...

    async def start(self, slots: Mapping[str, int]) -> None: ...

    async def enqueue(self, kind: str, args: Mapping[str, Any], *, queue: str, attempts: int) -> BackgroundJob: ...

    async def job(self, job: str) -> BackgroundJob | None: ...

    async def jobs(
        self, *, kind: str | None = None, state: BackgroundState | None = None, limit: int = 20
    ) -> list[BackgroundJob]: ...

    async def cancel(self, job: str) -> BackgroundJob | None: ...


@runtime_checkable
class SchedulePort(Protocol):
    """An engine that keeps a clock: `schedule` puts a fire on a cron before `start` — five fields, or six with seconds
    first, translated to the engine's own dialect —, fired once per tick, across processes for a durable engine."""

    def schedule(self, name: str, cron: str, fire: BackgroundFire) -> None: ...
