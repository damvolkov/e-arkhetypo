"""infra/background: the in-process task supervisor — jobs as tasks of one task group, retries, progress, cancel, clocks.

A job is a kind (registered once, with its handler) run on a queue with kwargs: it is queued at once, runs when its
queue has a free slot (`slots` at once per queue), retries until its `attempts` are spent, and settles `completed`,
`failed` or `cancelled`; the last `keep` settled ones stay readable. A schedule is a cron whose clock is a task of the
same group, so nothing outlives the process — or survives it. `BackgroundReport` is the reporter a work receives: the
latest snapshot it reports becomes the job's `progress`, written at most every `throttle` seconds and always once more
when the work ends.

The values here (job, state, run, handler) are the vocabulary of every queue: `ports/queue` speaks them, and
`engines/dispatch` prefers a durable engine and falls back to this supervisor when it is absent or unreachable."""

import dataclasses
import uuid
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum, auto
from itertools import islice
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, ClassVar, Final, Protocol, Self, runtime_checkable

import anyio
from croniter import croniter

from e_infra.infra.errors import QueueError
from e_infra.infra.logger import logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping
    from types import TracebackType

    from anyio.abc import TaskGroup

### seconds between two progress writes of one job: a fast work must not become a write storm.
THROTTLE: Final[float] = 0.5
### settled jobs the supervisor keeps for lookup; the oldest settled one leaves first.
KEEP: Final[int] = 1000


##### VALUES #####
class BackgroundState(StrEnum):
    """Where a job stands: waiting (`available`, `scheduled`, `retryable`), in flight (`running`, `waiting_external`),
    or settled (`completed`, `failed`, `cancelled`)."""

    AVAILABLE = auto()
    SCHEDULED = auto()
    RUNNING = auto()
    RETRYABLE = auto()
    WAITING_EXTERNAL = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()


SETTLED: Final[frozenset[BackgroundState]] = frozenset(
    {BackgroundState.COMPLETED, BackgroundState.FAILED, BackgroundState.CANCELLED}
)


@dataclass(frozen=True, slots=True)
class BackgroundJob:
    """One job as its engine holds it: `args` the work's kwargs, `progress` its latest snapshot, `errors` one message
    per failed attempt, oldest first."""

    id: str
    kind: str
    queue: str
    state: BackgroundState
    attempt: int
    args: Mapping[str, Any]
    created: datetime
    progress: Mapping[str, Any] | None = None
    errors: tuple[str, ...] = ()
    finished: datetime | None = None


type BackgroundReporter = Callable[[Mapping[str, Any]], Awaitable[None]]
type BackgroundWork = Callable[[Mapping[str, Any], BackgroundReporter], Awaitable[None]]
type BackgroundFire = Callable[[], Awaitable[None]]


@runtime_checkable
class BackgroundRun(Protocol):
    """A job in flight, as its engine hands it to the handler: the job, and where its progress is written."""

    @property
    def job(self) -> BackgroundJob: ...

    async def report(self, progress: Mapping[str, Any]) -> None: ...


type BackgroundHandler = Callable[[BackgroundRun], Awaitable[None]]


##### SUPERVISOR #####
@dataclass(slots=True)
class BackgroundTask:
    """A memory job: its latest copy, the scope that cancels it, and the event set once it has settled."""

    job: BackgroundJob
    scope: anyio.CancelScope = field(default_factory=anyio.CancelScope)
    done: anyio.Event = field(default_factory=anyio.Event)

    async def report(self, progress: Mapping[str, Any]) -> None:
        self.job = dataclasses.replace(self.job, progress=progress)


class Background:
    """Jobs as tasks of one anyio task group, `slots` at once per queue; the last `keep` settled ones stay readable;
    each schedule a clock task of the same group."""

    name: ClassVar[str] = "memory"

    __slots__ = ("_gates", "_group", "_handlers", "_keep", "_runs", "_schedules", "_stack")

    def __init__(self, keep: int = KEEP) -> None:
        self._keep = keep
        self._handlers: dict[str, BackgroundHandler] = {}
        self._schedules: dict[str, tuple[str, BackgroundFire]] = {}
        self._gates: Mapping[str, anyio.Semaphore] = MappingProxyType({})
        self._runs: dict[str, BackgroundTask] = {}
        self._stack = AsyncExitStack()
        self._group: TaskGroup | None = None

    ##### PRIVATE #####

    def _enqueue_group(self) -> TaskGroup:
        match self._group:
            case None:
                msg = "background is not entered: the lifespan opens it, callers never do"
                raise QueueError(msg)
            case group:
                return group

    def _enqueue_trim(self) -> None:
        """Drop the oldest settled job once more than `keep` are held."""
        oldest = next(iter(self._runs.values())) if len(self._runs) > self._keep else None
        _ = oldest and oldest.done.is_set() and self._runs.pop(oldest.job.id)

    async def _enqueue_run(self, run: BackgroundTask, handler: BackgroundHandler, attempts: int) -> None:
        try:
            with run.scope:
                async with self._gates[run.job.queue]:
                    await self._enqueue_attempt(run, handler, attempts)
        finally:
            ### whatever left the scope unsettled was cancelled — by `cancel`, or on exit.
            run.job = run.job if run.job.state in SETTLED else self._common_settle(run.job, BackgroundState.CANCELLED)
            run.done.set()

    async def _enqueue_attempt(self, run: BackgroundTask, handler: BackgroundHandler, left: int) -> None:
        run.job = dataclasses.replace(run.job, state=BackgroundState.RUNNING, attempt=run.job.attempt + 1)
        try:
            await handler(run)
        except Exception as failure:  # noqa: BLE001 — a failed attempt is a job state, never a crash of the engine
            errors = (*run.job.errors, f"{type(failure).__name__}: {failure}")
            run.job = dataclasses.replace(run.job, state=BackgroundState.RETRYABLE, errors=errors)
            match left:
                case 1:
                    run.job = self._common_settle(run.job, BackgroundState.FAILED)
                case _:
                    await self._enqueue_attempt(run, handler, left - 1)
            return
        run.job = self._common_settle(run.job, BackgroundState.COMPLETED)

    @classmethod
    async def _start_tick(cls, name: str, cron: str, fire: BackgroundFire) -> None:
        """A schedule's clock: sleep to the next tick, fire, again — a failed fire is said, the clock keeps going."""
        ### a clock is a loop by nature: one tick after another until the group is cancelled.
        while True:
            now = datetime.now(UTC)
            await anyio.sleep((cls.next_tick(cron, now) - now).total_seconds())
            try:
                await fire()
            except Exception as failure:  # noqa: BLE001 — a tick that failed is skipped, never the end of the clock
                logger.warning("schedule fire failed", schedule=name, error=f"{type(failure).__name__}: {failure}")

    @staticmethod
    def _common_settle(job: BackgroundJob, state: BackgroundState) -> BackgroundJob:
        return dataclasses.replace(job, state=state, finished=datetime.now(UTC))

    ############################################################

    ##### PUBLIC #####

    async def __aenter__(self) -> Self:
        self._group = self._group or await self._stack.enter_async_context(anyio.create_task_group())
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        _ = [run.scope.cancel() for run in self._runs.values()]
        ### the clocks never return by themselves: the group's own scope ends them with the runs.
        _ = self._group and self._group.cancel_scope.cancel()
        try:
            await self._stack.__aexit__(exc_type, exc, tb)
        finally:
            self._group = None

    def register(self, kind: str, queue: str, handler: BackgroundHandler) -> None:  # noqa: ARG002 — each job names its queue
        self._handlers[kind] = handler

    def schedule(self, name: str, cron: str, fire: BackgroundFire) -> None:
        self._schedules[name] = (cron, fire)

    @staticmethod
    def next_tick(cron: str, after: datetime) -> datetime:
        """The first tick of `cron` after `after`: five fields, or six with seconds first."""
        return croniter(cron, after, second_at_beginning=True).get_next(datetime)

    async def start(self, slots: Mapping[str, int]) -> None:
        self._gates = MappingProxyType({queue: anyio.Semaphore(count) for queue, count in slots.items()})
        group = self._enqueue_group()
        _ = [group.start_soon(self._start_tick, name, cron, fire) for name, (cron, fire) in self._schedules.items()]

    async def enqueue(self, kind: str, args: Mapping[str, Any], *, queue: str, attempts: int) -> BackgroundJob:
        group, handler = self._enqueue_group(), self._handlers[kind]
        job = BackgroundJob(
            id=uuid.uuid7().hex,
            kind=kind,
            queue=queue,
            state=BackgroundState.AVAILABLE,
            attempt=0,
            args=args,
            created=datetime.now(UTC),
        )
        self._runs[job.id] = run = BackgroundTask(job)
        self._enqueue_trim()
        group.start_soon(self._enqueue_run, run, handler, attempts)
        return job

    async def job(self, job: str) -> BackgroundJob | None:
        return run.job if (run := self._runs.get(job)) else None

    async def jobs(
        self, *, kind: str | None = None, state: BackgroundState | None = None, limit: int = 20
    ) -> list[BackgroundJob]:
        held = (run.job for run in reversed(self._runs.values()))
        return list(islice((job for job in held if kind in {None, job.kind} and state in {None, job.state}), limit))

    async def cancel(self, job: str) -> BackgroundJob | None:
        match self._runs.get(job):
            case None:
                return None
            case run:
                run.scope.cancel()
                await run.done.wait()
                return run.job


##### REPORTER #####
@dataclass(slots=True)
class BackgroundReport:
    """A run's reporter: the latest snapshot, written when THROTTLE has passed since the last write, and on `flush`."""

    run: BackgroundRun
    throttle: float
    pending: Mapping[str, Any] | None = None
    written: float = float("-inf")

    async def report(self, progress: Mapping[str, Any]) -> None:
        self.pending = progress
        _ = await self.flush() if anyio.current_time() - self.written >= self.throttle else None

    async def flush(self) -> None:
        match self.pending:
            case None:
                pass
            case pending:
                self.pending, self.written = None, anyio.current_time()
                await self.run.report(pending)
