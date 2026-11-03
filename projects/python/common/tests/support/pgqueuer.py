"""tests/support/pgqueuer: PgQueuer's own in-memory backend, shaped as the `Queries` the driver builds from a connection.

PgQueuer ships `PgQueuer.in_memory()` (pgqueuer 1.6, docs/reference/in-memory.md): `InMemoryQueries` over an
`InMemoryDriver`, no database. The driver builds `Queries(bridge)` over its ports; patching that name to answer one
shared `FakePgqueuerQueries` runs the real `QueueManager` and `SchedulerManager` — dequeue, heartbeat, retry, cancel,
cron — in memory, while the driver's own SQL (the `background.job` book) goes to the fake database. `bridges` keeps
every bridge it was built over, the scope each one rides. `schema_is_installed` is the one method the Postgres `Queries` has and the in-memory one does not."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pgqueuer.adapters.inmemory import InMemoryDriver, InMemoryQueries

if TYPE_CHECKING:
    from pgqueuer.domain.types import JobId


class FakePgqueuerDriver(InMemoryDriver):
    """PgQueuer's in-memory driver, answering the one SQL the driver sends itself — the cancel's log — by doing nothing:
    the in-memory backend logs a cancel when it applies it."""

    async def execute(self, query: str, *args: Any) -> str:
        return ""


@dataclass
class FakePgqueuerQueries(InMemoryQueries):
    """PgQueuer's in-memory queries, with the schema probe the driver asks first and a cancel's NOTIFY applied as the
    in-memory cancel (the log and the removal at once, as the server's listener would see them)."""

    async def schema_is_installed(self) -> bool:
        return False

    applying: bool = False

    async def notify_job_cancellation(self, ids: list[JobId]) -> None:
        """The driver's NOTIFY as the in-memory cancel; the cancel's own NOTIFY, inside it, is PgQueuer's."""
        match self.applying:
            case True:
                await super().notify_job_cancellation(ids)
            case False:
                self.applying = True
                try:
                    await self.mark_job_as_cancelled(ids)
                finally:
                    self.applying = False


class FakePgqueuer:
    """Stands for the `Queries` class: every bridge it is built over leads to the one in-memory backend."""

    def __init__(self) -> None:
        self.queries = FakePgqueuerQueries(driver=FakePgqueuerDriver())
        self.bridges: list[Any] = []

    def __call__(self, bridge: Any) -> FakePgqueuerQueries:
        self.bridges.append(bridge)
        return self.queries


def book_row(job: int = 1, **fields: Any) -> dict[str, Any]:
    """The `background.job` book's row for a job, as the driver's `READ` shapes it: queued and untouched unless asked."""
    base = {
        "id": job, "kind": "reported", "queue": "q", "args": '{"n": 1}', "created": datetime(2026, 10, 30, tzinfo=UTC),
        "progress": None, "live": "queued", "retries": 0, "execute_after": None, "last": None, "picks": 0,
        "errors": [], "finished": None, "state": "available",
    }  # fmt: skip
    return base | fields
