"""core/background: work that outlives the call that asked for it — one interface over a durable engine or memory.

A work is registered once by kind, on a queue, and submitted by kwargs: `await background.submit("annotate",
documents=(...), force=True)` answers at once with the job, queued. The work receives those kwargs and a reporter: each
snapshot it reports (plain builtins) becomes the job's `progress`, written at most every `throttle` seconds and always
once more when the work ends. A work that returns completes its job; one that raises is retried until its `attempts`
are spent; a cancel interrupts it where it awaits.

The engine is a `BackgroundPort`: a durable one (the awa adapter: Postgres, survives restarts, rescues crashed
workers) or `MemoryBackground` (a task group in this process; nothing survives it). `Background` always holds the
memory engine and prefers the durable one: an engine absent, unreachable on entry, or failing one enqueue sends the
work to memory with a warning, never a crash. A durable engine reports an outage as `BackgroundError`; any other error
is the caller's and propagates. Ids are strings, an engine's own, so a lookup asks memory first, then the durable."""

import dataclasses
import uuid
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum, auto
from functools import partial
from itertools import islice
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, ClassVar, Final, Protocol, Self, runtime_checkable

import anyio

from e_core.core.logger import logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping
    from types import TracebackType

    from anyio.abc import TaskGroup

### seconds between two progress writes of one job: a fast work must not become a write storm.
THROTTLE: Final[float] = 0.5
### settled jobs memory keeps for lookup; the oldest settled one leaves first.
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


class BackgroundError(RuntimeError):
    """A durable engine that cannot be reached: the work falls back to memory."""


type BackgroundReporter = Callable[[Mapping[str, Any]], Awaitable[None]]
type BackgroundWork = Callable[[Mapping[str, Any], BackgroundReporter], Awaitable[None]]


##### PORTS #####
@runtime_checkable
class BackgroundRun(Protocol):
    """A job in flight, as its engine hands it to the handler: the job, and where its progress is written."""

    @property
    def job(self) -> BackgroundJob: ...

    async def report(self, progress: Mapping[str, Any]) -> None: ...


type BackgroundHandler = Callable[[BackgroundRun], Awaitable[None]]


@runtime_checkable
class BackgroundPort(Protocol):
    """An engine: `register` binds a kind to its handler on a queue before `start` runs `slots` workers per queue; a
    handler that returns completes its job, one that raises retries it until `attempts` are spent. `job`, `jobs` and
    `cancel` read and settle what is held; an unknown id is None. `connect` and `close` bound its life."""

    name: ClassVar[str]

    async def connect(self) -> None: ...

    async def close(self) -> None: ...

    def register(self, kind: str, queue: str, handler: BackgroundHandler) -> None: ...

    async def start(self, slots: Mapping[str, int]) -> None: ...

    async def enqueue(self, kind: str, args: Mapping[str, Any], *, queue: str, attempts: int) -> BackgroundJob: ...

    async def job(self, job: str) -> BackgroundJob | None: ...

    async def jobs(
        self, *, kind: str | None = None, state: BackgroundState | None = None, limit: int = 20
    ) -> list[BackgroundJob]: ...

    async def cancel(self, job: str) -> BackgroundJob | None: ...


##### MEMORY #####
@dataclass(slots=True)
class MemoryRun:
    """A memory job: its latest copy, the scope that cancels it, and the event set once it has settled."""

    job: BackgroundJob
    scope: anyio.CancelScope = field(default_factory=anyio.CancelScope)
    done: anyio.Event = field(default_factory=anyio.Event)

    async def report(self, progress: Mapping[str, Any]) -> None:
        self.job = dataclasses.replace(self.job, progress=progress)


class MemoryBackground:
    """Jobs as tasks of one anyio task group, `slots` at once per queue; the last `keep` settled ones stay readable."""

    name: ClassVar[str] = "memory"

    __slots__ = ("_gates", "_group", "_handlers", "_keep", "_runs", "_stack")

    def __init__(self, keep: int = KEEP) -> None:
        self._keep = keep
        self._handlers: dict[str, BackgroundHandler] = {}
        self._gates: Mapping[str, anyio.Semaphore] = MappingProxyType({})
        self._runs: dict[str, MemoryRun] = {}
        self._stack = AsyncExitStack()
        self._group: TaskGroup | None = None

    ##### PRIVATE #####

    def _enqueue_group(self) -> TaskGroup:
        match self._group:
            case None:
                msg = "memory background is not connected"
                raise BackgroundError(msg)
            case group:
                return group

    def _enqueue_trim(self) -> None:
        """Drop the oldest settled job once more than `keep` are held."""
        oldest = next(iter(self._runs.values())) if len(self._runs) > self._keep else None
        _ = oldest and oldest.done.is_set() and self._runs.pop(oldest.job.id)

    async def _enqueue_run(self, run: MemoryRun, handler: BackgroundHandler, attempts: int) -> None:
        try:
            with run.scope:
                async with self._gates[run.job.queue]:
                    await self._enqueue_attempt(run, handler, attempts)
        finally:
            ### whatever left the scope unsettled was cancelled — by `cancel`, or by `close`.
            run.job = run.job if run.job.state in SETTLED else self._common_settle(run.job, BackgroundState.CANCELLED)
            run.done.set()

    async def _enqueue_attempt(self, run: MemoryRun, handler: BackgroundHandler, left: int) -> None:
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

    @staticmethod
    def _common_settle(job: BackgroundJob, state: BackgroundState) -> BackgroundJob:
        return dataclasses.replace(job, state=state, finished=datetime.now(UTC))

    ############################################################

    ##### PUBLIC #####

    async def connect(self) -> None:
        self._group = self._group or await self._stack.enter_async_context(anyio.create_task_group())

    async def close(self) -> None:
        _ = [run.scope.cancel() for run in self._runs.values()]
        try:
            await self._stack.aclose()
        finally:
            self._group = None

    def register(self, kind: str, queue: str, handler: BackgroundHandler) -> None:  # noqa: ARG002 — each job names its queue
        self._handlers[kind] = handler

    async def start(self, slots: Mapping[str, int]) -> None:
        self._gates = MappingProxyType({queue: anyio.Semaphore(count) for queue, count in slots.items()})

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
        self._runs[job.id] = run = MemoryRun(job)
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


##### FACADE #####
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


class Background:
    """Background work by kind, on the durable engine when it answers, in memory when it does not."""

    __slots__ = ("_durable", "_memory", "_slots", "_stack", "_throttle", "_works")

    def __init__(self, durable: BackgroundPort | None, slots: Mapping[str, int], *, throttle: float = THROTTLE) -> None:
        self._durable = durable
        self._memory = MemoryBackground()
        self._slots = MappingProxyType(dict(slots))
        self._throttle = throttle
        self._works: dict[str, tuple[str, BackgroundWork]] = {}
        self._stack = AsyncExitStack()

    ##### PRIVATE #####

    async def _register_run(self, work: BackgroundWork, run: BackgroundRun) -> None:
        reporter = BackgroundReport(run, self._throttle)
        try:
            await work(run.job.args, reporter.report)
        finally:
            with anyio.CancelScope(shield=True):
                await reporter.flush()

    def _common_bind(self, engine: BackgroundPort) -> None:
        _ = [
            engine.register(kind, queue, partial(self._register_run, work))
            for kind, (queue, work) in self._works.items()
        ]

    async def _common_enter(self, engine: BackgroundPort) -> None:
        await engine.connect()
        self._stack.push_async_callback(engine.close)
        self._common_bind(engine)
        await engine.start(self._slots)

    async def _common_durable(self) -> BackgroundPort | None:
        """The durable engine entered, or None — absent, or unreachable: a warning, and memory alone."""
        match self._durable:
            case None:
                logger.warning("background in memory: jobs will not survive a restart", step="START")
                return None
            case durable:
                try:
                    await self._common_enter(durable)
                except BackgroundError as error:
                    logger.warning(
                        "background engine unreachable, in memory: jobs will not survive a restart",
                        engine=durable.name,
                        error=str(error),
                        step="START",
                    )
                    return None
                return durable

    async def _submit_durable(self, kind: str, args: Mapping[str, Any], attempts: int) -> BackgroundJob | None:
        queue = self._works[kind][0]
        match self._durable:
            case None:
                return None
            case durable:
                try:
                    return await durable.enqueue(kind, args, queue=queue, attempts=attempts)
                except BackgroundError as error:
                    logger.warning("background enqueue fell back to memory", kind=kind, error=str(error))
                    return None

    async def _common_read[T](self, read: Callable[[BackgroundPort], Awaitable[T]], empty: T) -> T:
        """A read of the durable engine, or `empty` when there is none or it fails — with a warning."""
        match self._durable:
            case None:
                return empty
            case durable:
                try:
                    return await read(durable)
                except BackgroundError as error:
                    logger.warning("background engine unreadable", engine=durable.name, error=str(error))
                    return empty

    ############################################################

    ##### PUBLIC #####

    @property
    def engine(self) -> str:
        """The engine new jobs go to: the durable one's name, or `memory`."""
        return self._durable.name if self._durable else self._memory.name

    def register(self, kind: str, work: BackgroundWork, *, queue: str = "default") -> None:
        """Bind a kind to its work on a queue; every kind is registered before the facade is entered."""
        self._works[kind] = (queue, work)

    async def submit(self, kind: str, /, *, attempts: int = 1, **args: Any) -> BackgroundJob:
        """Queue a job of `kind` whose work receives `args`; it comes back queued."""
        durable = await self._submit_durable(kind, args, attempts)
        return durable or await self._memory.enqueue(kind, args, queue=self._works[kind][0], attempts=attempts)

    async def job(self, job: str) -> BackgroundJob | None:
        """One job by id, from memory or the durable engine; None when unknown."""
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
        await self._common_enter(self._memory)
        self._durable = await self._common_durable()
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        await self._stack.__aexit__(exc_type, exc, tb)
