"""providers/drivers/queue/pgqueuer: the default durable queue, PgQueuer behind `QueuePort` and `SchedulePort`.

It rides the database it is handed — a `DatabasePort` and a `ListenPort`, met by either Postgres driver, the lifespan
opening it first and closing it last — and opens no pool of its own. PgQueuer reaches the database through its own
`Driver` port, met here by `PgqueuerBridge` over ours: statements on a scope of the database — the pool, one transaction
(an enqueue and its record), one connection (the schema's session lock) —, LISTEN on the database's `ListenPort`, one
connection the database driver holds for every channel. The database's pool serves every manager at once: at least six
connections (fewer stalls a manager under load, measured on e-gnosis). A database that fails under it is a `QueueError`.

PgQueuer has no queues, only entrypoints: each port queue is one entrypoint, the kind travels in the payload and picks
the handler. A queue's `slots` is the entrypoint's `concurrency_limit`, counted in SQL over every worker of the
database (fleet-wide, not per process): PgQueuer refuses a per-worker cap below twice its batch, so a
slot of one is only expressible this way. A settled job leaves PgQueuer's queue table (its log keeps status, picks and
tracebacks, never the payload), so this driver keeps each job's kind, queue, args, attempts and latest snapshot in
`background.job`, written in the enqueue's own transaction. Retries are the driver's: a failed attempt with attempts
left raises `RetryRequested`. Each queue runs one `QueueManager`; a manager that dies is restarted by a supervisor after
QUEUE_RESTART — PgQueuer does not restart by itself.

Schedules are PgQueuer's own: one `SchedulerManager`, supervised like the managers, keeps every schedule in PgQueuer's
schedules table and claims each due tick in the database, so a tick fires once across every process holding the
schedule; the fire runs in this process."""

import asyncio
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import partial
from typing import TYPE_CHECKING, ClassVar, Final, Self, cast

import anyio
import msgspec
from pgqueuer.adapters.persistence.queries import Queries
from pgqueuer.core.qm import QueueManager
from pgqueuer.core.sm import SchedulerManager
from pgqueuer.core.tm import TaskManager
from pgqueuer.domain.errors import RetryRequested
from pgqueuer.domain.types import JobId

from e_infra.infra.background import BackgroundJob, BackgroundState
from e_infra.infra.errors import DatabaseError, ProviderError, QueueError
from e_infra.infra.logger import logger
from e_infra.ports.provider import Isolation, Locality, Opened, ProviderSpec, Workload

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

    from pgqueuer.domain.models import Context, Job, Schedule
    from pgqueuer.ports.driver import NotifyCallback

    from e_infra.infra.background import BackgroundFire, BackgroundHandler
    from e_infra.infra.payload import JSON
    from e_infra.ports.database import Cell, DatabasePort, ListenPort, QueryPort, Row

### a cron with a seconds field: six fields.
SECONDS: Final[int] = 6

SCHEMA: Final[tuple[str, ...]] = (
    "CREATE SCHEMA IF NOT EXISTS background",
    (
        "CREATE TABLE IF NOT EXISTS background.job ("
        "id bigint PRIMARY KEY, kind text NOT NULL, queue text NOT NULL, args jsonb NOT NULL, attempts int NOT NULL, "
        "created timestamptz NOT NULL DEFAULT now(), progress jsonb)"
    ),
    "CREATE INDEX IF NOT EXISTS job_kind_created ON background.job (kind, created DESC)",
)
RECORD: Final[str] = "INSERT INTO background.job (id, kind, queue, args, attempts) VALUES ($1, $2, $3, $4::jsonb, $5)"
REPORT: Final[str] = "UPDATE background.job SET progress = $2::jsonb WHERE id = $1"
### one row per job: the queue row while it lives, else the log's last word; picks count the attempts; a retry's
### traceback is PgQueuer's RetryRequested, whose message is the failure it carries.
READ: Final[str] = """
SELECT j.id, j.kind, j.queue, j.args::text AS args, j.created, j.progress::text AS progress,
       q.status::text AS live, q.attempts AS retries, q.execute_after,
       l.last::text AS last, l.picks, l.errors, l.finished,
       CASE
           WHEN q.status = 'picked' THEN 'running'
           WHEN q.status = 'queued' AND q.execute_after > now() THEN
               CASE WHEN q.attempts > 0 THEN 'retryable' ELSE 'scheduled' END
           WHEN q.status = 'queued' THEN CASE WHEN q.attempts > 0 THEN 'retryable' ELSE 'available' END
           WHEN q.status = 'failed' THEN 'failed'
           WHEN l.last = 'successful' THEN 'completed'
           WHEN l.last IN ('exception', 'failed') THEN 'failed'
           WHEN l.last IN ('canceled', 'deleted') THEN 'cancelled'
           ELSE 'available'
       END AS state
FROM background.job j
LEFT JOIN pgqueuer q ON q.id = j.id
LEFT JOIN LATERAL (
    SELECT (array_agg(status ORDER BY created DESC, id DESC)
                FILTER (WHERE status NOT IN ('queued', 'picked')))[1] AS last,
           count(*) FILTER (WHERE status = 'picked') AS picks,
           coalesce(array_agg(CASE traceback->>'exception_type' WHEN 'RetryRequested' THEN traceback->>'exception_message'
                ELSE (traceback->>'exception_type') || ': ' || (traceback->>'exception_message') END
                ORDER BY created, id) FILTER (WHERE traceback IS NOT NULL), '{}') AS errors,
           max(created) FILTER (WHERE status NOT IN ('queued', 'picked')) AS finished
    FROM pgqueuer_log WHERE job_id = j.id
) l ON true
"""
ONE: Final[str] = f"SELECT * FROM ({READ}) r WHERE id = $1"  # noqa: S608 — constants only, values bound
WHERE: Final[str] = "($1::text IS NULL OR kind = $1) AND ($2::text IS NULL OR state = $2)"
MANY: Final[str] = f"SELECT * FROM ({READ}) r WHERE {WHERE} ORDER BY created DESC, id DESC LIMIT $3"  # noqa: S608 — constants only, values bound
### a cancel already logged for the job: what a NOTIFY that came before the job's scope existed would have said.
CANCELLED: Final[str] = "SELECT 1 FROM pgqueuer_log WHERE job_id = $1 AND status IN ('canceled', 'deleted') LIMIT 1"


##### BRIDGE #####
class PgqueuerBridge:
    """PgQueuer's `Driver` over the ports: its statements on one `QueryPort` scope, its LISTEN on the database's
    `ListenPort`; leaving it unlistens what it listened. Text without parameters is a script — PgQueuer's install is
    several statements in one."""

    __slots__ = ("_heard", "_listen", "_on", "_shutdown")

    def __init__(self, on: QueryPort, listen: ListenPort) -> None:
        self._on = on
        self._listen = listen
        self._shutdown = asyncio.Event()
        self._heard: list[tuple[str, NotifyCallback]] = []

    ##### PRIVATE #####

    ### PgQueuer's `Driver` hands `object`; ty cannot know that what it binds is a `Cell` (invalid-argument-type).
    @staticmethod
    def _common_cells(args: tuple[object, ...]) -> Sequence[Cell]:  # ast-grep-ignore: object-annotation
        """What PgQueuer binds, as the port takes it."""
        return cast("Sequence[Cell]", args)  # ast-grep-ignore: cast

    ############################################################

    ##### PUBLIC #####

    ### PgQueuer's `Driver` fixes `object` for what it binds and returns.
    async def fetch(self, query: str, *args: object) -> list[dict[str, object]]:  # ast-grep-ignore: object-annotation
        return [dict(row) for row in await self._on.fetch(query, self._common_cells(args))]

    ### same: the `Driver` port's own signature.
    async def execute(self, query: str, *args: object) -> str:  # ast-grep-ignore: object-annotation
        _ = await (self._on.execute(query, self._common_cells(args)) if args else self._on.script(query))
        return ""

    async def notify(self, channel: str, payload: str) -> None:
        await self._on.execute("SELECT pg_notify($1, $2)", [channel, payload])

    async def add_listener(self, channel: str, callback: NotifyCallback) -> None:
        self._heard.append((channel, callback))
        await self._listen.listen(channel, callback)

    async def remove_listener(self, channel: str, callback: NotifyCallback) -> None:
        _ = (channel, callback) in self._heard and self._heard.remove((channel, callback))
        await self._listen.unlisten(channel, callback)

    @property
    def shutdown(self) -> asyncio.Event:
        return self._shutdown

    @property
    def tm(self) -> TaskManager:
        return TaskManager()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_exit: object) -> None:
        heard, self._heard = self._heard, []
        _ = [await self._listen.unlisten(channel, callback) for channel, callback in heard]


class PgqueuerRow(msgspec.Struct, frozen=True, kw_only=True):
    """The columns of `READ` this driver reads; `args` and `progress` are JSON text."""

    id: int
    kind: str
    queue: str
    state: str
    args: str
    created: datetime
    live: str | None = None
    picks: int | None = None
    progress: str | None = None
    errors: Sequence[str] | None = None
    finished: datetime | None = None


@dataclass(frozen=True, slots=True)
class PgqueuerRun:
    """A job in flight on PgQueuer: the job as it was picked, and the writer of its snapshot."""

    job: BackgroundJob
    write: Callable[[Mapping[str, JSON]], Awaitable[None]]

    async def report(self, progress: Mapping[str, JSON]) -> None:
        await self.write(progress)


##### DRIVER #####
class PgqueuerDriver:
    """PgQueuer managers, one per queue, behind `QueuePort` and `SchedulePort`, on the database it is handed."""

    spec: ClassVar[ProviderSpec] = ProviderSpec(
        "pgqueuer", Locality.REMOTE, Workload.IO_BOUND, Isolation.LOOP, pooled=True
    )
    ### the event a close sets: held from the open to the close's end, it is what "entered" means.
    closing = Opened[anyio.Event](QueueError)

    __slots__ = (
        "_closing",
        "_db",
        "_drain",
        "_handlers",
        "_heartbeat",
        "_listen",
        "_managers",
        "_poll",
        "_restart",
        "_scheduler",
        "_schedules",
        "_supervisors",
        "_timeout",
    )

    def __init__(
        self,
        database: DatabasePort,
        listen: ListenPort,
        *,
        timeout: timedelta,
        poll: timedelta,
        drain: timedelta,
        heartbeat: timedelta,
        restart: timedelta,
    ) -> None:
        self._timeout, self._poll, self._drain, self._heartbeat, self._restart = (
            timeout,
            poll,
            drain,
            heartbeat,
            restart,
        )
        self._db = database
        self._listen = listen
        self._handlers: dict[str, tuple[str, BackgroundHandler]] = {}
        self._managers: dict[str, QueueManager] = {}
        self._schedules: dict[str, tuple[str, BackgroundFire]] = {}
        self._scheduler: SchedulerManager | None = None
        ### plain tasks, not a task group: a group entered in `__aenter__` cannot be left under `__aexit__`'s deadline.
        self._supervisors: set[asyncio.Task[None]] = set()
        self._closing: anyio.Event | None = None

    ##### PRIVATE #####

    async def _enter_schema(self) -> None:
        """PgQueuer's schema installed or upgraded under its session lock, on one connection; then the driver's."""
        async with self._db.connection() as held:
            queries = Queries(PgqueuerBridge(held, self._listen))
            _ = await queries.upgrade() if await queries.schema_is_installed() else await queries.install()
            _ = [await held.execute(statement) for statement in SCHEMA]
        logger.debug("pgqueuer schema installed")

    def _common_queries(self, on: QueryPort | None = None) -> Queries:
        """PgQueuer's queries over a scope of the database (the pool by default), listening on the database."""
        return Queries(PgqueuerBridge(on or self._db, self._listen))

    async def _start_supervise(self, queue: str, slots: int) -> None:
        """One manager for `queue`, started again whenever it dies, until close."""
        closing = self.closing
        while not closing.is_set():
            try:
                await self._start_manage(queue, slots)
            except Exception as error:  # noqa: BLE001 — a dead manager is restarted, never a crash of the engine
                logger.warning(
                    "pgqueuer manager died, restarting", queue=queue, error=f"{type(error).__name__}: {error}"
                )
            with anyio.move_on_after(self._restart.total_seconds()):
                await closing.wait()

    async def _start_manage(self, queue: str, slots: int) -> None:
        manager = QueueManager(self._common_queries())
        manager.entrypoint(queue, concurrency_limit=slots, accepts_context=True)(self._register_run)
        self._managers[queue] = manager
        logger.debug("pgqueuer manager started", queue=queue, slots=slots)
        ### a close that came while starting must still stop this manager.
        _ = self.closing.is_set() and manager.shutdown.set()
        try:
            await manager.run(
                dequeue_timeout=self._poll,
                batch_size=1,
                heartbeat_timeout=self._heartbeat,
                shutdown_on_listener_failure=True,
            )
        finally:
            self._managers.pop(queue, None)

    async def _start_clock(self) -> None:
        """The scheduler for every schedule, started again whenever it dies, until close."""
        closing = self.closing
        while not closing.is_set():
            try:
                await self._start_schedule()
            except Exception as error:  # noqa: BLE001 — a dead scheduler is restarted, never a crash of the engine
                logger.warning("pgqueuer scheduler died, restarting", error=f"{type(error).__name__}: {error}")
            with anyio.move_on_after(self._restart.total_seconds()):
                await closing.wait()

    async def _start_schedule(self) -> None:
        scheduler = SchedulerManager(self._common_queries())
        _ = [
            scheduler.schedule(name, self.dialect(cron))(partial(self._start_tick, fire))
            for name, (cron, fire) in self._schedules.items()
        ]
        self._scheduler = scheduler
        logger.debug("pgqueuer scheduler started", schedules=len(self._schedules))
        _ = self.closing.is_set() and scheduler.shutdown.set()
        try:
            await scheduler.run()
        finally:
            self._scheduler = None

    @staticmethod
    async def _start_tick(fire: BackgroundFire, _schedule: Schedule) -> None:
        await fire()

    async def _close_drain(self) -> None:
        """Supervisors given QUEUE_DRAIN to return with their jobs done; past it they are cancelled, jobs with them."""
        tasks, self._supervisors = self._supervisors, set()
        _, late = await asyncio.wait(tasks, timeout=self._drain.total_seconds()) if tasks else (set(), set())
        _ = [task.cancel() for task in late]
        _ = late and await asyncio.wait(late)

    async def _register_run(self, job: Job, context: Context) -> None:
        body = json.loads(job.payload or b"{}")
        attempts = int(str((job.headers or {}).get("attempts", 1)))
        handler = self._handlers[body["kind"]][1]
        found = BackgroundJob(
            id=str(job.id),
            kind=body["kind"],
            queue=str(job.entrypoint),
            state=BackgroundState.RUNNING,
            attempt=job.attempts + 1,
            args=body["args"],
            created=job.created,
        )
        ### a cancel NOTIFY cancels this scope; PgQueuer leaves entering it to the entrypoint. A NOTIFY that came
        ### between the pick and the scope's registration found no scope and was dropped: the log, written before
        ### every NOTIFY (`cancel`), is read once now — a job cancelled by then never starts.
        with context.cancellation:
            match await self._register_cancelled(job.id):
                case True:
                    context.cancellation.cancel()
                case _:
                    try:
                        await handler(PgqueuerRun(found, lambda progress: self._register_report(job.id, progress)))
                    except Exception as error:
                        _ = job.attempts + 1 < attempts and self._register_retry(error)
                        raise

    @staticmethod
    def _register_retry(error: Exception) -> None:
        raise RetryRequested(delay=timedelta(0), reason=f"{type(error).__name__}: {error}") from error

    async def _register_cancelled(self, job: int) -> bool:
        """Whether the job's cancel is already logged."""
        return bool(await self._common_call(lambda: self._db.fetch(CANCELLED, [job])))

    async def _cancel_ordered(self, job: JobId) -> None:
        """PgQueuer's cancel in order: the log written, then the NOTIFY — its own sends both at once, so a NOTIFY could
        land before the log a late-registered job reads."""
        queries = self._common_queries()
        await queries.driver.execute(queries.qbq.build_log_job_query(), [job], ["canceled"], [None])
        await queries.notify_job_cancellation([job])

    async def _register_report(self, job: int, progress: Mapping[str, JSON]) -> None:
        ### a JSON parameter travels as a Python value: each driver binds it as jsonb (text would bind as a JSON string).
        await self._common_call(lambda: self._db.execute(REPORT, [job, json.loads(json.dumps(progress))]))

    async def _common_call[T](self, call: Callable[[], Awaitable[T]]) -> T:
        """One call within QUEUE_TIMEOUT; a database that fails under it is the port's `QueueError`."""
        try:
            with anyio.fail_after(self._timeout.total_seconds()):
                return await call()
        ### TimeoutError is an OSError: caught first, or a slow call would read as an empty outage.
        except TimeoutError as error:
            msg = f"pgqueuer call timed out after {self._timeout}"
            logger.error("pgqueuer call timed out", timeout=str(self._timeout))
            raise QueueError(msg) from error
        except (OSError, DatabaseError) as error:
            logger.error("pgqueuer database failed", error=str(error))
            raise QueueError(str(error)) from error

    @staticmethod
    def _common_job(row: Row) -> BackgroundJob:
        found = msgspec.convert(row, PgqueuerRow, strict=False)
        return BackgroundJob(
            id=str(found.id),
            kind=found.kind,
            queue=found.queue,
            state=BackgroundState(found.state),
            attempt=max(found.picks or 0, 1 if found.live == "picked" else 0),
            args=json.loads(found.args),
            created=found.created,
            progress=json.loads(found.progress) if found.progress else None,
            errors=tuple(found.errors or ()),
            finished=found.finished if found.state in {"completed", "failed", "cancelled"} else None,
        )

    ############################################################

    ##### PUBLIC #####

    async def __aenter__(self) -> Self:
        await self._common_call(self._enter_schema)
        self._closing = anyio.Event()
        logger.info("pgqueuer opened")
        return self

    async def health(self) -> bool:
        """The driver is entered and its database answers one query within QUEUE_TIMEOUT."""
        try:
            _ = self.closing
            await self._common_call(lambda: self._db.fetch("SELECT 1"))
        except ProviderError as error:
            logger.warning("pgqueuer unhealthy", error=str(error))
            raise
        return True

    async def __aexit__(self, *exc: object) -> None:
        """Managers stop picking and drain for QUEUE_DRAIN; past it their jobs are cancelled. The database is its
        owner's, closed with it. The whole is bounded by QUEUE_DRAIN + 2 QUEUE_TIMEOUT."""
        self.closing.set()
        _ = [manager.shutdown.set() for manager in tuple(self._managers.values())]
        _ = self._scheduler and self._scheduler.shutdown.set()
        limit = self._drain + self._timeout * 2
        try:
            with anyio.fail_after(limit.total_seconds()):
                await self._close_drain()
        except TimeoutError as error:
            msg = f"pgqueuer close timed out after {limit}"
            logger.error("pgqueuer close timed out", limit=str(limit))
            raise QueueError(msg) from error
        finally:
            self._closing = None
        logger.info("pgqueuer closed")

    def register(self, kind: str, queue: str, handler: BackgroundHandler) -> None:
        self._handlers[kind] = (queue, handler)

    def schedule(self, name: str, cron: str, fire: BackgroundFire) -> None:
        self._schedules[name] = (cron, fire)

    @staticmethod
    def dialect(cron: str) -> str:
        """The port's cron in PgQueuer's (croniter's): six fields read seconds last, so the first moves to the end."""
        fields = cron.split()
        return " ".join([*fields[1:], fields[0]]) if len(fields) == SECONDS else cron

    async def start(self, slots: Mapping[str, int]) -> None:
        _ = self.closing
        self._supervisors |= {
            asyncio.create_task(self._start_supervise(queue, count)) for queue, count in slots.items()
        }
        self._supervisors |= {asyncio.create_task(self._start_clock())} if self._schedules else set()

    async def enqueue(self, kind: str, args: Mapping[str, JSON], *, queue: str, attempts: int) -> BackgroundJob:
        plain = json.loads(json.dumps(args))

        async def insert() -> int:
            async with self._db.transaction() as tx:
                payload = json.dumps({"kind": kind, "args": plain}).encode()
                ids = await self._common_queries(tx).enqueue(queue, payload, headers={"attempts": str(attempts)})
                await tx.execute(RECORD, [ids[0], kind, queue, plain, attempts])
                return ids[0]

        found = await self.job(str(await self._common_call(insert)))
        match found:
            case None:
                msg = "pgqueuer lost a job it just enqueued"
                raise QueueError(msg)
            case job:
                return job

    async def job(self, job: str) -> BackgroundJob | None:
        row = await self._common_call(lambda: self._db.row(ONE, [int(job)])) if job.isdecimal() else None
        return self._common_job(row) if row else None

    async def jobs(
        self, *, kind: str | None = None, state: BackgroundState | None = None, limit: int = 20
    ) -> list[BackgroundJob]:
        rows = await self._common_call(lambda: self._db.fetch(MANY, [kind, state and str(state), limit]))
        return [self._common_job(row) for row in rows]

    async def cancel(self, job: str) -> BackgroundJob | None:
        """A queued or running job is logged cancelled and its row deleted at once; a running one is interrupted by
        PgQueuer's NOTIFY where it awaits. A settled one comes back unchanged."""
        _ = job.isdecimal() and await self._common_call(lambda: self._cancel_ordered(JobId(int(job))))
        return await self.job(job)
