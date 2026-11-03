"""tests/support/awa: an awa client that holds no database — jobs in a dict, SQL recorded, failures scripted.

awa has no fake of its own, and its client is a Rust runtime. A `FakeAwaClient` is the client at the level the driver
calls: `migrate`, `transaction` (its `execute` and `fetch_all` recorded, answering scripted rows), `task`, `start`,
`insert`, `get_job`, `list_jobs`, `cancel`, `shutdown`, `close`. A job is a `FakeAwaJob` with the fields the driver
reads. Failures are scripted by method name and raised as awa's own exceptions (`DatabaseError`, `AwaError`). The driver
is patched to build it: `monkeypatch.setattr(awa_module, "AsyncClient", client)`."""

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable, Sequence

type Row = dict[str, Any]


@dataclass(slots=True)
class FakeAwaJob:
    """A job as awa's `Job` shows it to the driver."""

    id: int
    kind: str
    queue: str
    args: dict[str, Any]
    state: str = "available"
    attempt: int = 0
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    finalized_at: str | None = None
    errors: list[dict[str, str]] = field(default_factory=list)
    cancelled: bool = False

    def is_cancelled(self) -> bool:
        return self.cancelled


class FakeAwaTransaction:
    """`client.transaction()`: statements recorded on the client, rows answered by a fragment of the statement."""

    def __init__(self, client: FakeAwaClient) -> None:
        self._client = client

    async def execute(self, query: str, *params: object) -> None:
        self._client.statements.append((query, params))
        self._client.fail("execute")

    async def fetch_all(self, query: str, *params: object) -> list[Row]:
        self._client.statements.append((query, params))
        self._client.fail("fetch_all")
        return next((rows for fragment, rows in self._client.answers.items() if fragment in query), [])


class FakeAwaClient:
    """`AsyncClient(dsn, max_connections=…)`: one per driver, shared state in plain attributes."""

    def __init__(self, dsn: str, max_connections: int = 10) -> None:
        self.dsn = dsn
        self.max_connections = max_connections
        self.jobs: dict[int, FakeAwaJob] = {}
        self.answers: dict[str, list[Row]] = {}
        self.failures: dict[str, BaseException] = {}
        self.statements: list[tuple[str, tuple[object, ...]]] = []
        self.tasks: dict[str, Callable[..., Any]] = {}
        self.started: list[tuple[list[tuple[str, int]], int]] = []
        self.calls: list[str] = []
        self.opened = 0
        self.closed = False
        self.drained: int | None = None

    def fail(self, method: str) -> None:
        """Raise what is scripted for `method`, once per call."""
        self.calls.append(method)
        if method in self.failures:
            raise self.failures[method]

    def sql(self) -> list[str]:
        return [query for query, _ in self.statements]

    @asynccontextmanager
    async def _scope(self) -> AsyncGenerator[FakeAwaTransaction]:
        self.opened += 1
        yield FakeAwaTransaction(self)

    async def transaction(self) -> Any:
        """Awaited for an async context manager, as awa's: `async with await client.transaction() as tx`."""
        self.fail("transaction")
        return self._scope()

    async def migrate(self) -> None:
        self.fail("migrate")

    def task(self, _kind: type, *, kind: str, queue: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def register(handler: Callable[..., Any]) -> Callable[..., Any]:
            self.tasks[kind] = handler
            return handler

        return register

    async def start(self, queues: Sequence[tuple[str, int]], *, poll_interval_ms: int) -> None:
        self.fail("start")
        self.started.append((list(queues), poll_interval_ms))

    async def insert(self, args: dict[str, Any], *, kind: str, queue: str, max_attempts: int) -> FakeAwaJob:
        self.fail("insert")
        job = FakeAwaJob(id=len(self.jobs) + 1, kind=kind, queue=queue, args=args)
        self.jobs[job.id] = job
        return job

    async def get_job(self, job: int) -> FakeAwaJob | None:
        self.fail("get_job")
        return self.jobs.get(job)

    async def list_jobs(self, *, kind: str | None, state: str | None, limit: int) -> list[FakeAwaJob]:
        self.fail("list_jobs")
        found = [j for j in self.jobs.values() if kind in (None, j.kind) and state in (None, j.state)]
        return sorted(found, key=lambda j: j.id, reverse=True)[:limit]

    async def cancel(self, job: int) -> FakeAwaJob | None:
        self.fail("cancel")
        match self.jobs.get(job):
            case None:
                return None
            case found if found.state in {"completed", "failed", "cancelled"}:
                return None
            case found:
                found.state, found.cancelled = "cancelled", True
                return found

    async def shutdown(self, timeout_ms: int = 2000) -> None:
        self.fail("shutdown")
        self.drained = timeout_ms

    async def close(self) -> None:
        self.fail("close")
        self.closed = True
