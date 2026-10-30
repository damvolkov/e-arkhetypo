"""providers/drivers/awa: the durable queue — awa, a Rust Postgres job queue, behind `QueuePort`.

awa's runtime is tokio and sqlx; its Python handlers run on the app's own event loop. The queue lives in a database
of its own (`QUEUE_DSN`), apart from the service's data. `__aenter__` builds the client off the
loop (its constructor connects synchronously) within `QUEUE_TIMEOUT`, migrates awa's schema and this driver's own
`background.progress` table — awa clears a job's progress when it completes, so the latest snapshot of each job is
kept there, upserted on every report — then opens the whole pool (`QUEUE_POOL`) at once: an awa pool that must grow
while the server refuses it a connection (out of slots) stalls its runtime — no claim, no shutdown — until one frees,
so a pool not granted whole within `QUEUE_TIMEOUT` is an outage now, never a stall later. Ids cross the port as
strings; an outage (`DatabaseError`, a timeout) is a `QueueError`, and so is a call that outlasts `QUEUE_TIMEOUT`
(a host that never answers would hold it for the driver's thirty seconds); anything else propagates. Once the database
answers again awa reconnects by itself. A cancel lands in storage at once; a handler in flight learns it by polling
`is_cancelled` every `QUEUE_POLL`, and its scope is cancelled where it awaits. `__aexit__` drains the workers for
`QUEUE_DRAIN`, then releases the pool, all within `QUEUE_DRAIN` + `QUEUE_TIMEOUT`: past it, a `QueueError`."""

import json
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from itertools import count
from typing import TYPE_CHECKING, Any, ClassVar, Final, Self

import anyio
import msgspec
from awa import AsyncClient, AwaError, Cancel, Job
from awa import DatabaseError as AwaDatabaseError

from e_infra.infra.background import BackgroundJob, BackgroundState
from e_infra.infra.errors import ProviderError, QueueError
from e_infra.infra.settings import settings as st
from e_infra.ports.provider import Isolation, Locality, ProviderSpec, Workload

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

    from e_infra.infra.background import BackgroundHandler
    from e_infra.infra.config.queue import QueueSettings

SCHEMA: Final[tuple[str, ...]] = (
    "CREATE SCHEMA IF NOT EXISTS background",
    (
        "CREATE TABLE IF NOT EXISTS background.progress ("
        "job bigint PRIMARY KEY, snapshot jsonb NOT NULL, updated timestamptz NOT NULL DEFAULT now())"
    ),
)
REPORT: Final[str] = (
    "INSERT INTO background.progress (job, snapshot) VALUES ($1, $2::jsonb) "
    "ON CONFLICT (job) DO UPDATE SET snapshot = EXCLUDED.snapshot, updated = now()"
)
### awa binds no array parameter: the ids travel as one JSON array.
SNAPSHOTS: Final[str] = (
    "SELECT job, snapshot FROM background.progress WHERE job IN (SELECT jsonb_array_elements_text($1::jsonb)::bigint)"
)


@dataclass(frozen=True, slots=True)
class AwaRun:
    """A job in flight on awa: the job as it was claimed, and the writer of its snapshot."""

    job: BackgroundJob
    write: Callable[[Mapping[str, Any]], Awaitable[None]]

    async def report(self, progress: Mapping[str, Any]) -> None:
        await self.write(progress)


class AwaDriver:
    """An awa client behind `QueuePort`."""

    spec: ClassVar[ProviderSpec] = ProviderSpec("awa", Locality.REMOTE, Workload.IO_BOUND, Isolation.LOOP, pooled=True)

    __slots__ = ("_client", "_conf")

    def __init__(self, settings: QueueSettings | None = None) -> None:
        ### the default is read on call, not at import: the settings singleton stays lazy.
        self._conf = st.queue if settings is None else settings
        self._client: AsyncClient | None = None

    ##### PRIVATE #####

    async def _enter_client(self) -> AsyncClient:
        build = partial(AsyncClient, self._conf.dsn.get_secret_value(), max_connections=self._conf.pool)
        with anyio.fail_after(self._conf.timeout.total_seconds()):
            return await anyio.to_thread.run_sync(build, abandon_on_cancel=True)

    async def _enter_fill(self, client: AsyncClient) -> None:
        """Every connection of the pool opened now, each held until all are: a pool that must grow later stalls the
        runtime (no claim, no shutdown) while the server refuses it a connection, where a refusal now is an outage."""
        async with AsyncExitStack() as stack:
            _ = [await stack.enter_async_context(await client.transaction()) for _ in range(self._conf.pool)]

    async def _register_run(self, handler: BackgroundHandler, job: Job[dict[str, Any]]) -> Cancel | None:
        try:
            async with anyio.create_task_group() as group:
                group.start_soon(self._register_watch, job, group.cancel_scope)
                await handler(AwaRun(self._common_job(job, None), partial(self._register_report, job.id)))
                group.cancel_scope.cancel()
        except* Exception as failed:  # noqa: BLE001 — unwrapped and re-raised, never swallowed
            ### the watcher never raises: the one error is the handler's, recorded by awa as itself, not as a group.
            raise failed.exceptions[0] from None
        ### a cancel caught mid-work is settled as one: returning plainly would claim the work completed.
        return Cancel() if job.is_cancelled() else None

    async def _register_report(self, job: int, progress: Mapping[str, Any]) -> None:
        await self._common_execute(REPORT, job, json.dumps(progress))

    async def _register_watch(self, job: Job[dict[str, Any]], scope: anyio.CancelScope) -> None:
        _ = await anext(tick for tick in count() if await self._register_cancelled(job))
        scope.cancel()

    async def _register_cancelled(self, job: Job[dict[str, Any]]) -> bool:
        await anyio.sleep(self._conf.poll.total_seconds())
        return job.is_cancelled()

    async def _common_snapshots(self, ids: list[int]) -> dict[int, dict[str, Any]]:
        rows = await self._common_fetch(SNAPSHOTS, json.dumps(ids)) if ids else []
        return {row["job"]: row["snapshot"] for row in rows}

    async def _common_execute(self, query: str, *params: object, bounded: bool = True) -> None:
        async def run(client: AsyncClient) -> None:
            async with await client.transaction() as tx:
                await tx.execute(query, *params)

        await self._common_call(run, bounded=bounded)

    async def _common_fetch(self, query: str, *params: object) -> list[dict[str, Any]]:
        async def run(client: AsyncClient) -> list[dict[str, Any]]:
            ### returned after the block: awa's transaction may swallow an exit, so the type checker wants the rows bound.
            async with await client.transaction() as tx:
                rows = await tx.fetch_all(query, *params)
            return rows  # noqa: RET504

        return await self._common_call(run)

    async def _common_call[T](self, call: Callable[[AsyncClient], Awaitable[T]], *, bounded: bool = True) -> T:
        """One call on the client, within QUEUE_TIMEOUT when `bounded`; an outage of the database is the port's
        `QueueError`."""
        try:
            with anyio.fail_after(self._conf.timeout.total_seconds() if bounded else None):
                return await call(self._common_client())
        except AwaDatabaseError as error:
            raise QueueError(str(error)) from error
        except TimeoutError as error:
            msg = f"awa call timed out after {self._conf.timeout}"
            raise QueueError(msg) from error

    async def _common_found(
        self, call: Callable[[AsyncClient], Awaitable[Job[dict[str, Any]] | None]]
    ) -> BackgroundJob | None:
        """The job a call returns with its snapshot, or None when its id is unknown to awa."""
        try:
            found = await self._common_call(call)
        except AwaError as error:
            match str(error).partition(":")[0]:
                case "job not found":
                    return None
                case _:
                    raise
        match found:
            case None:
                return None
            case job:
                return self._common_job(job, (await self._common_snapshots([job.id])).get(job.id))

    @staticmethod
    def _common_job(job: Job[dict[str, Any]], progress: Mapping[str, Any] | None) -> BackgroundJob:
        return BackgroundJob(
            id=str(job.id),
            kind=job.kind,
            queue=job.queue,
            state=BackgroundState(str(job.state)),
            attempt=job.attempt,
            args=job.args,
            created=datetime.fromisoformat(job.created_at),
            progress=progress,
            errors=tuple(str(error.get("error", "")).partition("\n")[0] for error in job.errors),
            finished=datetime.fromisoformat(job.finalized_at) if job.finalized_at else None,
        )

    def _common_client(self) -> AsyncClient:
        match self._client:
            case None:
                msg = "AwaDriver is not open: the lifespan opens it, callers never do"
                raise QueueError(msg)
            case client:
                return client

    ############################################################

    ##### PUBLIC #####

    async def __aenter__(self) -> Self:
        try:
            self._client = self._client or await self._enter_client()
        except (AwaDatabaseError, TimeoutError) as error:
            raise QueueError(str(error) or "awa open timed out") from error
        ### the schema is one-time work — awa's first migrate takes seconds on a fresh database: it is never cut short.
        await self._common_call(lambda client: client.migrate(), bounded=False)
        _ = [await self._common_execute(statement, bounded=False) for statement in SCHEMA]
        await self._common_call(self._enter_fill)
        return self

    async def health(self) -> bool:
        """One trivial query on the queue's database, within QUEUE_TIMEOUT."""
        try:
            await self._common_fetch("SELECT 1")
        except ProviderError:
            return False
        return True

    async def __aexit__(self, *exc: object) -> None:
        match self._client:
            case None:
                pass
            case client:
                ### awa bounds only the drain: its dispatchers, services and pool are awaited without end.
                limit = self._conf.drain + self._conf.timeout
                try:
                    with anyio.fail_after(limit.total_seconds()):
                        await client.shutdown(int(self._conf.drain.total_seconds() * 1000))
                        await client.close()
                except TimeoutError as error:
                    msg = f"awa close timed out after {limit}"
                    raise QueueError(msg) from error
                finally:
                    self._client = None

    def register(self, kind: str, queue: str, handler: BackgroundHandler) -> None:
        _ = self._common_client().task(dict, kind=kind, queue=queue)(partial(self._register_run, handler))

    async def start(self, slots: Mapping[str, int]) -> None:
        poll = int(self._conf.poll.total_seconds() * 1000)
        await self._common_call(lambda client: client.start(list(slots.items()), poll_interval_ms=poll))

    async def enqueue(self, kind: str, args: Mapping[str, Any], *, queue: str, attempts: int) -> BackgroundJob:
        ### awa takes JSON types only: a tuple (any sequence field of a struct's builtins) goes through as a list.
        plain = msgspec.json.decode(msgspec.json.encode(args))
        job = await self._common_call(
            lambda client: client.insert(plain, kind=kind, queue=queue, max_attempts=attempts)
        )
        return self._common_job(job, None)

    async def job(self, job: str) -> BackgroundJob | None:
        return await self._common_found(lambda client: client.get_job(int(job))) if job.isdecimal() else None

    async def jobs(
        self, *, kind: str | None = None, state: BackgroundState | None = None, limit: int = 20
    ) -> list[BackgroundJob]:
        found = await self._common_call(lambda client: client.list_jobs(kind=kind, state=state, limit=limit))
        snapshots = await self._common_snapshots([job.id for job in found])
        return [self._common_job(job, snapshots.get(job.id)) for job in found]

    async def cancel(self, job: str) -> BackgroundJob | None:
        ### awa answers None for a job already settled: the port answers the job, unchanged.
        cancelled = await self._common_found(lambda client: client.cancel(int(job))) if job.isdecimal() else None
        return cancelled or await self.job(job)
