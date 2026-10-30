"""providers/drivers/queue/pgqueuer: the default durable queue, PgQueuer on asyncpg, behind `QueuePort` and `SchedulePort`.

It rides an `AsyncpgDriver` received by constructor — the lifespan opens that one first and closes it last — and opens
no pool of its own: client calls go through the driver's pool, and each queue manager and the scheduler hold a
dedicated connection the driver opens for them. A database that fails under it is a `QueueError`.

PgQueuer has no queues, only entrypoints: each port queue is one entrypoint, the kind travels in the payload and picks
the handler. A queue's `slots` is the entrypoint's `concurrency_limit`, counted in SQL over every worker of the
database (fleet-wide, not per process): PgQueuer refuses a per-worker cap below twice its batch, so a
slot of one is only expressible this way. A settled job leaves PgQueuer's queue table (its log keeps status, picks and
tracebacks, never the payload), so this driver keeps each job's kind, queue, args, attempts and latest snapshot in
`background.job`, written in the enqueue's own transaction. Retries are the driver's: a failed attempt with attempts
left raises `RetryRequested`. Each queue runs one `QueueManager` on a connection of its own (LISTEN, dequeue,
heartbeats); a manager that dies with its connection is restarted by a supervisor after QUEUE_RESTART — PgQueuer does not
reconnect by itself. Client calls (enqueue, reads, cancel, progress) go through the driver's pool.

Schedules are PgQueuer's own: one `SchedulerManager`, on a connection of its own and supervised like the managers,
keeps every schedule in PgQueuer's schedules table and claims each due tick in the database, so a tick fires once
across every process holding the schedule; the fire runs in this process."""

import asyncio
import json
from dataclasses import dataclass
from datetime import timedelta
from functools import partial
from typing import TYPE_CHECKING, Any, ClassVar, Final, Protocol, Self

import anyio
from pgqueuer.adapters.persistence.queries import Queries
from pgqueuer.core.qm import QueueManager
from pgqueuer.core.sm import SchedulerManager
from pgqueuer.domain.errors import RetryRequested
from pgqueuer.domain.types import JobId

from e_infra.infra.background import BackgroundJob, BackgroundState
from e_infra.infra.errors import DatabaseError, ProviderError, QueueError
from e_infra.infra.logger import logger
from e_infra.infra.settings import settings as st
from e_infra.ports.provider import Isolation, Locality, ProviderSpec, Workload

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping
    from contextlib import AbstractAsyncContextManager, AbstractContextManager

    import asyncpg
    from pgqueuer.domain.models import Context, Job, Schedule

    from e_infra.infra.background import BackgroundFire, BackgroundHandler
    from e_infra.infra.config.providers.drivers.queue.pgqueuer import PgqueuerSettings

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


##### HOST #####
class PgqueuerHost(Protocol):
    """What PgQueuer needs of the asyncpg driver it rides: its pool, a connection of its own, the error border. The
    driver (`providers/drivers/database/asyncpg`) satisfies it structurally — a provider never imports another."""

    @property
    def pool(self) -> asyncpg.Pool: ...

    def connection(self) -> AbstractAsyncContextManager[asyncpg.Connection]: ...

    def guard(self) -> AbstractContextManager[None]: ...


@dataclass(frozen=True, slots=True)
class PgqueuerRun:
    """A job in flight on PgQueuer: the job as it was picked, and the writer of its snapshot."""

    job: BackgroundJob
    write: Callable[[Mapping[str, Any]], Awaitable[None]]

    async def report(self, progress: Mapping[str, Any]) -> None:
        await self.write(progress)


class PgqueuerDriver:
    """PgQueuer managers, one per queue, behind `QueuePort` and `SchedulePort`."""

    spec: ClassVar[ProviderSpec] = ProviderSpec(
        "pgqueuer", Locality.REMOTE, Workload.IO_BOUND, Isolation.LOOP, pooled=True
    )

    __slots__ = (
        "_closing",
        "_conf",
        "_db",
        "_handlers",
        "_managers",
        "_open",
        "_scheduler",
        "_schedules",
        "_supervisors",
    )

    def __init__(self, database: PgqueuerHost, settings: PgqueuerSettings | None = None) -> None:
        ### the default is read on call, not at import: the settings singleton stays lazy.
        self._conf = st.providers.drivers.queue.pgqueuer if settings is None else settings
        self._db = database
        self._open = False
        self._handlers: dict[str, tuple[str, BackgroundHandler]] = {}
        self._managers: dict[str, QueueManager] = {}
        self._schedules: dict[str, tuple[str, BackgroundFire]] = {}
        self._scheduler: SchedulerManager | None = None
        ### plain tasks, not a task group: a group entered in `__aenter__` cannot be left under `__aexit__`'s deadline.
        self._supervisors: set[asyncio.Task[None]] = set()
        self._closing = anyio.Event()

    ##### PRIVATE #####

    async def _enter_schema(self, pool: asyncpg.Pool) -> None:
        async with pool.acquire() as connection:
            queries = Queries.from_asyncpg_connection(connection)
            _ = await queries.upgrade() if await queries.schema_is_installed() else await queries.install()
            _ = [await connection.execute(statement) for statement in SCHEMA]
        logger.debug("pgqueuer schema installed")

    def _start_check(self) -> None:
        """The driver's pool is open, or the queue cannot start: a `QueueError`, never a manager dying in a loop."""
        try:
            _ = self._db.pool
        except DatabaseError as error:
            raise QueueError(str(error)) from error

    async def _start_supervise(self, queue: str, slots: int) -> None:
        """One manager for `queue`, started again on a fresh connection whenever it dies, until close."""
        while not self._closing.is_set():
            try:
                await self._start_manage(queue, slots)
            except Exception as error:  # noqa: BLE001 — a dead manager is restarted, never a crash of the engine
                logger.warning(
                    "pgqueuer manager died, restarting", queue=queue, error=f"{type(error).__name__}: {error}"
                )
            with anyio.move_on_after(self._conf.restart.total_seconds()):
                await self._closing.wait()

    async def _start_manage(self, queue: str, slots: int) -> None:
        async with self._db.connection() as connection:
            manager = QueueManager(Queries.from_asyncpg_connection(connection))
            manager.entrypoint(queue, concurrency_limit=slots, accepts_context=True)(self._register_run)
            self._managers[queue] = manager
            logger.debug("pgqueuer manager started", queue=queue, slots=slots)
            try:
                ### a close that came while connecting must still stop this manager.
                _ = self._closing.is_set() and manager.shutdown.set()
                await manager.run(
                    dequeue_timeout=self._conf.poll,
                    batch_size=1,
                    heartbeat_timeout=self._conf.heartbeat,
                    shutdown_on_listener_failure=True,
                )
            finally:
                self._managers.pop(queue, None)

    async def _start_clock(self) -> None:
        """The scheduler for every schedule, started again on a fresh connection whenever it dies, until close."""
        while not self._closing.is_set():
            try:
                await self._start_schedule()
            except Exception as error:  # noqa: BLE001 — a dead scheduler is restarted, never a crash of the engine
                logger.warning("pgqueuer scheduler died, restarting", error=f"{type(error).__name__}: {error}")
            with anyio.move_on_after(self._conf.restart.total_seconds()):
                await self._closing.wait()

    async def _start_schedule(self) -> None:
        async with self._db.connection() as connection:
            scheduler = SchedulerManager(Queries.from_asyncpg_connection(connection))
            _ = [
                scheduler.schedule(name, self.dialect(cron))(partial(self._start_tick, fire))
                for name, (cron, fire) in self._schedules.items()
            ]
            self._scheduler = scheduler
            logger.debug("pgqueuer scheduler started", schedules=len(self._schedules))
            try:
                _ = self._closing.is_set() and scheduler.shutdown.set()
                await scheduler.run()
            finally:
                self._scheduler = None

    @staticmethod
    async def _start_tick(fire: BackgroundFire, _schedule: Schedule) -> None:
        await fire()

    async def _close_drain(self) -> None:
        """Supervisors given QUEUE_DRAIN to return with their jobs done; past it they are cancelled, jobs with them."""
        tasks, self._supervisors = self._supervisors, set()
        _, late = await asyncio.wait(tasks, timeout=self._conf.drain.total_seconds()) if tasks else (set(), set())
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
        ### a cancel NOTIFY cancels this scope; PgQueuer leaves entering it to the entrypoint.
        with context.cancellation:
            try:
                await handler(PgqueuerRun(found, lambda progress: self._register_report(job.id, progress)))
            except Exception as error:
                _ = job.attempts + 1 < attempts and self._register_retry(error)
                raise

    @staticmethod
    def _register_retry(error: Exception) -> None:
        raise RetryRequested(delay=timedelta(0), reason=f"{type(error).__name__}: {error}") from error

    async def _register_report(self, job: int, progress: Mapping[str, Any]) -> None:
        await self._common_call(lambda pool: pool.execute(REPORT, job, json.dumps(progress)))

    async def _common_call[T](self, call: Callable[[asyncpg.Pool], Awaitable[T]]) -> T:
        """One call on the driver's pool within QUEUE_TIMEOUT; a database that fails under it is the port's
        `QueueError`."""
        try:
            with anyio.fail_after(self._conf.timeout.total_seconds()), self._db.guard():
                return await call(self._db.pool)
        except TimeoutError as error:
            msg = f"pgqueuer call timed out after {self._conf.timeout}"
            logger.error("pgqueuer call timed out", timeout=str(self._conf.timeout))
            raise QueueError(msg) from error
        except DatabaseError as error:
            logger.error("pgqueuer database failed", error=str(error))
            raise QueueError(str(error)) from error

    @staticmethod
    def _common_job(row: Mapping[str, Any]) -> BackgroundJob:
        return BackgroundJob(
            id=str(row["id"]),
            kind=row["kind"],
            queue=row["queue"],
            state=BackgroundState(row["state"]),
            attempt=max(row["picks"] or 0, 1 if row["live"] == "picked" else 0),
            args=json.loads(row["args"]),
            created=row["created"],
            progress=json.loads(row["progress"]) if row["progress"] else None,
            errors=tuple(row["errors"] or ()),
            finished=row["finished"] if row["state"] in {"completed", "failed", "cancelled"} else None,
        )

    ############################################################

    ##### PUBLIC #####

    async def __aenter__(self) -> Self:
        await self._common_call(self._enter_schema)
        self._closing = anyio.Event()
        self._open = True
        logger.info("pgqueuer opened")
        return self

    async def health(self) -> bool:
        """The driver is entered and its database answers one query within QUEUE_TIMEOUT."""
        match self._open:
            case False:
                logger.warning("pgqueuer unhealthy", reason="not open")
                return False
            case True:
                pass
        try:
            await self._common_call(lambda pool: pool.fetchval("SELECT 1"))
        except ProviderError as error:
            logger.warning("pgqueuer unhealthy", error=str(error))
            return False
        return True

    async def __aexit__(self, *exc: object) -> None:
        """Managers stop picking and drain for QUEUE_DRAIN; past it their jobs are cancelled. The pool is the driver's,
        closed with it. The whole is bounded by QUEUE_DRAIN + QUEUE_TIMEOUT."""
        self._closing.set()
        self._open = False
        _ = [manager.shutdown.set() for manager in tuple(self._managers.values())]
        _ = self._scheduler and self._scheduler.shutdown.set()
        limit = self._conf.drain + self._conf.timeout
        try:
            with anyio.fail_after(limit.total_seconds()):
                await self._close_drain()
        except TimeoutError as error:
            msg = f"pgqueuer close timed out after {limit}"
            logger.error("pgqueuer close timed out", limit=str(limit))
            raise QueueError(msg) from error
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
        self._start_check()
        self._supervisors |= {
            asyncio.create_task(self._start_supervise(queue, count)) for queue, count in slots.items()
        }
        self._supervisors |= {asyncio.create_task(self._start_clock())} if self._schedules else set()

    async def enqueue(self, kind: str, args: Mapping[str, Any], *, queue: str, attempts: int) -> BackgroundJob:
        plain = json.loads(json.dumps(args))

        async def insert(pool: asyncpg.Pool) -> int:
            async with pool.acquire() as connection, connection.transaction():
                payload = json.dumps({"kind": kind, "args": plain}).encode()
                ids = await Queries.from_asyncpg_connection(connection).enqueue(
                    queue, payload, headers={"attempts": str(attempts)}
                )
                await connection.execute(RECORD, ids[0], kind, queue, json.dumps(plain), attempts)
                return ids[0]

        found = await self.job(str(await self._common_call(insert)))
        match found:
            case None:
                msg = "pgqueuer lost a job it just enqueued"
                raise QueueError(msg)
            case job:
                return job

    async def job(self, job: str) -> BackgroundJob | None:
        row = await self._common_call(lambda pool: pool.fetchrow(ONE, int(job))) if job.isdecimal() else None
        return self._common_job(row) if row else None

    async def jobs(
        self, *, kind: str | None = None, state: BackgroundState | None = None, limit: int = 20
    ) -> list[BackgroundJob]:
        rows = await self._common_call(lambda pool: pool.fetch(MANY, kind, state and str(state), limit))
        return [self._common_job(row) for row in rows]

    async def cancel(self, job: str) -> BackgroundJob | None:
        """A queued or running job is logged cancelled and its row deleted at once; a running one is interrupted by
        PgQueuer's NOTIFY where it awaits. A settled one comes back unchanged."""

        async def mark(pool: asyncpg.Pool) -> None:
            async with pool.acquire() as connection:
                await Queries.from_asyncpg_connection(connection).mark_job_as_cancelled([JobId(int(job))])

        _ = job.isdecimal() and await self._common_call(mark)
        return await self.job(job)
