"""engines/dispatch: background work by kind — on the durable queue when it answers, in memory when it does not.

A work is registered once by kind, on a queue, and submitted by kwargs: `await dispatch.submit("annotate",
documents=(...), force=True)` answers at once with the job, queued. The work receives those kwargs and a reporter: each
snapshot it reports (plain builtins) becomes the job's `progress`, written at most every `throttle` seconds and always
once more when the work ends. A work that returns completes its job; one that raises is retried until its `attempts`
are spent; a cancel interrupts it where it awaits.

The engine holds the in-process supervisor (`infra/background`) and prefers the durable `QueuePort`: a queue absent,
unreachable on entry, or failing one enqueue sends the work to memory with a warning, never a crash. A durable queue
reports an outage as `QueueError`; any other error is the caller's and propagates. Ids are strings, a queue's own, so a
lookup asks memory first, then the durable.

A schedule puts a registered kind on a cron: on each tick the engine submits it, coalesced, so a run that has not
started yet absorbs the next tick; the work itself always runs as a job, with its retries, progress and record. The
clock belongs to the durable queue when it keeps one (`SchedulePort`: one fire per tick across every process),
else to the supervisor. Which concrete queue is the durable one is the composition root's decision, never this module's."""

import json
from contextlib import AsyncExitStack
from dataclasses import dataclass
from functools import partial
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final, Self

import anyio
from croniter import croniter

from e_infra.infra.background import (
    THROTTLE,
    Background,
    BackgroundJob,
    BackgroundReport,
    BackgroundRun,
    BackgroundState,
    BackgroundWork,
)
from e_infra.infra.errors import QueueError
from e_infra.infra.logger import logger
from e_infra.ports.queue import QueuePort, SchedulePort

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping
    from types import TracebackType

    type Engine = QueuePort | Background

### the waiting jobs a coalesced submit looks among: past them a twin is queued anew — wasteful, never wrong.
WAITING: Final[int] = 100


@dataclass(frozen=True, slots=True)
class BackgroundSchedule:
    """A kind on a cron: on each tick its job is submitted with `args`, coalesced."""

    name: str
    cron: str
    kind: str
    args: Mapping[str, Any]


class DispatchEngine:
    """Background work by kind, on the durable queue when it answers, in memory when it does not."""

    __slots__ = ("_durable", "_memory", "_schedules", "_slots", "_stack", "_throttle", "_works")

    def __init__(
        self,
        durable: QueuePort | None,
        memory: Background,
        slots: Mapping[str, int],
        *,
        throttle: float = THROTTLE,
    ) -> None:
        self._durable = durable
        self._memory = memory
        self._slots = MappingProxyType(dict(slots))
        self._throttle = throttle
        self._works: dict[str, tuple[str, BackgroundWork]] = {}
        self._schedules: dict[str, BackgroundSchedule] = {}
        self._stack = AsyncExitStack()

    ##### PRIVATE #####

    async def _register_run(self, work: BackgroundWork, run: BackgroundRun) -> None:
        reporter = BackgroundReport(run, self._throttle)
        try:
            await work(run.job.args, reporter.report)
        finally:
            with anyio.CancelScope(shield=True):
                await reporter.flush()

    async def _schedule_fire(self, schedule: BackgroundSchedule) -> None:
        """One tick: the schedule's kind submitted, coalesced; a tick that cannot be submitted is said and skipped."""
        try:
            job = await self.submit(schedule.kind, coalesce=True, **schedule.args)
        except Exception as failure:  # noqa: BLE001 — a tick that failed is skipped, never the end of the clock
            logger.warning(
                "schedule fired in vain", schedule=schedule.name, error=f"{type(failure).__name__}: {failure}"
            )
            return
        logger.info("schedule fired", schedule=schedule.name, kind=schedule.kind, job=job.id, step="SCHEDULE")

    def _common_bind(self, engine: Engine, *, clock: bool) -> None:
        """Every work on the engine; every schedule too when it keeps the clock."""
        _ = [
            engine.register(kind, queue, partial(self._register_run, work))
            for kind, (queue, work) in self._works.items()
        ]
        match engine:
            case SchedulePort() if clock:
                _ = [
                    engine.schedule(each.name, each.cron, partial(self._schedule_fire, each))
                    for each in self._schedules.values()
                ]
            case _:
                pass

    async def _common_enter(self, engine: Engine, *, clock: bool) -> None:
        await self._stack.enter_async_context(engine)
        self._common_bind(engine, clock=clock)
        await engine.start(self._slots)

    async def _common_durable(self) -> QueuePort | None:
        """The durable queue entered, or None — absent, or unreachable: a warning, and memory alone."""
        match self._durable:
            case None:
                logger.warning("background in memory: jobs will not survive a restart", step="START")
                return None
            case durable:
                try:
                    await self._common_enter(durable, clock=True)
                except QueueError as error:
                    logger.warning(
                        "background queue unreachable, in memory: jobs will not survive a restart",
                        engine=durable.spec.name,
                        error=str(error),
                        step="START",
                    )
                    return None
                return durable

    @staticmethod
    def _submit_plain(args: Mapping[str, Any]) -> str:
        """Arguments as a queue keeps them — JSON, keys sorted —: what tells the same submit from another."""
        return json.dumps(json.loads(json.dumps(args, default=str)), sort_keys=True)

    async def _submit_waiting(self, kind: str, args: Mapping[str, Any]) -> BackgroundJob | None:
        """The same kind and arguments already queued and not yet started, if any."""
        plain = self._submit_plain(args)
        waiting = await self.jobs(kind=kind, state=BackgroundState.AVAILABLE, limit=WAITING)
        return next((job for job in waiting if self._submit_plain(job.args) == plain), None)

    async def _submit_durable(self, kind: str, args: Mapping[str, Any], attempts: int) -> BackgroundJob | None:
        queue = self._works[kind][0]
        match self._durable:
            case None:
                return None
            case durable:
                try:
                    return await durable.enqueue(kind, args, queue=queue, attempts=attempts)
                except QueueError as error:
                    logger.warning("background enqueue fell back to memory", kind=kind, error=str(error))
                    return None

    async def _common_read[T](self, read: Callable[[QueuePort], Awaitable[T]], empty: T) -> T:
        """A read of the durable queue, or `empty` when there is none or it fails — with a warning."""
        match self._durable:
            case None:
                return empty
            case durable:
                try:
                    return await read(durable)
                except QueueError as error:
                    logger.warning("background queue unreadable", engine=durable.spec.name, error=str(error))
                    return empty

    ############################################################

    ##### PUBLIC #####

    @property
    def engine(self) -> str:
        """The queue new jobs go to: the durable one's name, or `memory`."""
        return self._durable.spec.name if self._durable else self._memory.name

    async def health(self) -> bool:
        """The durable queue answers; in memory it does not (its jobs would not survive a restart)."""
        match self._durable:
            case None:
                return False
            case durable:
                return await durable.health()

    def register(self, kind: str, work: BackgroundWork, *, queue: str = "default") -> None:
        """Bind a kind to its work on a queue; every kind is registered before the engine is entered."""
        self._works[kind] = (queue, work)

    def schedule(self, name: str, cron: str, kind: str, /, **args: Any) -> None:
        """Put a registered kind on a cron (five fields, or six with seconds first): each tick submits it with `args`,
        coalesced. A name is one schedule; registering it again replaces it."""
        match (croniter.is_valid(cron, second_at_beginning=True), kind in self._works):
            case (False, _):
                message = f"schedule {name!r}: {cron!r} is no cron expression"
                raise ValueError(message)
            case (_, False):
                message = f"schedule {name!r}: no work registered for kind {kind!r}"
                raise LookupError(message)
            case _:
                self._schedules[name] = BackgroundSchedule(name=name, cron=cron, kind=kind, args=args)

    async def submit(self, kind: str, /, *, attempts: int = 1, coalesce: bool = False, **args: Any) -> BackgroundJob:
        """Queue a job of `kind` whose work receives `args`; it comes back queued. Coalesced, the same kind and
        arguments already waiting to start is the job: one pending at most, however often asked."""
        waiting = await self._submit_waiting(kind, args) if coalesce else None
        durable = waiting or await self._submit_durable(kind, args, attempts)
        return durable or await self._memory.enqueue(kind, args, queue=self._works[kind][0], attempts=attempts)

    async def job(self, job: str) -> BackgroundJob | None:
        """One job by id, from memory or the durable queue; None when unknown."""
        return held if (held := await self._memory.job(job)) else await self._common_read(lambda e: e.job(job), None)

    async def jobs(
        self, *, kind: str | None = None, state: BackgroundState | None = None, limit: int = 20
    ) -> list[BackgroundJob]:
        """The latest jobs of both engines, newest first."""
        durable = await self._common_read(lambda e: e.jobs(kind=kind, state=state, limit=limit), [])
        held = await self._memory.jobs(kind=kind, state=state, limit=limit)
        return sorted((*durable, *held), key=lambda job: job.created, reverse=True)[:limit]

    async def cancel(self, job: str) -> BackgroundJob | None:
        """Cancel a waiting or running job; a settled one comes back unchanged, an unknown one None."""
        match await self._memory.job(job):
            case None:
                return await self._common_read(lambda e: e.cancel(job), None)
            case _:
                return await self._memory.cancel(job)

    async def __aenter__(self) -> Self:
        """Enter the durable queue (it keeps the clock when it can), then memory (which keeps it otherwise)."""
        self._durable = await self._common_durable()
        await self._common_enter(self._memory, clock=not isinstance(self._durable, SchedulePort))
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        await self._stack.__aexit__(exc_type, exc, tb)
