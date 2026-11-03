"""tests/support/pgqueuer: PgQueuer's own in-memory backend, shaped as the `Queries` the driver builds from a connection.

PgQueuer ships `PgQueuer.in_memory()` (pgqueuer 1.6, docs/reference/in-memory.md): `InMemoryQueries` over an
`InMemoryDriver`, no database. The driver calls `Queries.from_asyncpg_connection(connection)` in five places; patching
that name to answer one shared `FakePgqueuerQueries` runs the real `QueueManager` and `SchedulerManager` — dequeue,
heartbeat, retry, cancel, cron — in memory, while the driver's own SQL (the `background.job` book) goes to the fake asyncpg
pool. `schema_is_installed` is the one method the Postgres `Queries` has and the in-memory one does not."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pgqueuer.adapters.inmemory import InMemoryDriver, InMemoryQueries


@dataclass
class FakePgqueuerQueries(InMemoryQueries):
    """PgQueuer's in-memory queries, with the schema probe the driver asks first."""

    async def schema_is_installed(self) -> bool:
        return False


class FakePgqueuer:
    """Stands for the `Queries` class: every connection it is asked about leads to the one in-memory backend."""

    def __init__(self) -> None:
        self.queries = FakePgqueuerQueries(driver=InMemoryDriver())

    def from_asyncpg_connection(self, _connection: Any) -> FakePgqueuerQueries:
        return self.queries


def book_row(job: int = 1, **fields: Any) -> dict[str, Any]:
    """The `background.job` book's row for a job, as the driver's `READ` shapes it: queued and untouched unless asked."""
    base = {
        "id": job, "kind": "reported", "queue": "q", "args": '{"n": 1}', "created": datetime(2026, 10, 30, tzinfo=UTC),
        "progress": None, "live": "queued", "retries": 0, "execute_after": None, "last": None, "picks": 0,
        "errors": [], "finished": None, "state": "available",
    }  # fmt: skip
    return base | fields
