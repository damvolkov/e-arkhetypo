"""tests/support/psqlpy: a psqlpy pool, connection and transaction that hold no database — rows scripted, SQL recorded.

psqlpy has no fake of its own. A `FakePsqlpyServer` is what the pools of one test share: answers by a fragment of the
statement, failures by a fragment (raised as psqlpy's own `Error`), and every statement run, in order, with its
parameters. The driver is patched to build `FakePsqlpyPool`s: `monkeypatch.setattr(psqlpy_module, "ConnectionPool",
server.pool)`. `held` counts connections taken and not given back — a cancelled call must leave it at zero."""

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import anyio

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable, Sequence

type Row = dict[str, Any]


class FakePsqlpyResult:
    """What `fetch` returns: rows behind `.result()`, as psqlpy's `QueryResult`."""

    def __init__(self, rows: list[Row]) -> None:
        self._rows = rows

    def result(self) -> list[Row]:
        return list(self._rows)


@dataclass(slots=True)
class FakePsqlpyServer:
    """The shared state of every pool built in one test."""

    answers: dict[str, list[Row] | Callable[[], list[Row]]] = field(default_factory=dict)
    failures: dict[str, Exception] = field(default_factory=dict)
    hang: str = ""
    refuse: Exception | None = None
    statements: list[tuple[str, list[object]]] = field(default_factory=list)
    transactions: list[str] = field(default_factory=list)
    pools: list[FakePsqlpyPool] = field(default_factory=list)
    held: int = 0

    def run(self, query: str, params: Sequence[object] | None) -> list[Row]:
        """Record the statement, raise the failure scripted for it, else answer the rows scripted for it."""
        self.statements.append((query, list(params or ())))
        for fragment, failure in self.failures.items():
            if fragment in query:
                raise failure
        answer = next((rows for fragment, rows in self.answers.items() if fragment in query), [])
        match answer:
            case list():
                return answer
            case produce:
                return produce()

    async def stall(self, query: str) -> None:
        """A statement that never answers, until its caller is cancelled."""
        _ = self.hang and self.hang in query and await anyio.sleep_forever()

    def pool(self, **kwargs: Any) -> FakePsqlpyPool:
        """`ConnectionPool(dsn=…, max_db_pool_size=…, connect_timeout_sec=…)`, as the driver builds it."""
        built = FakePsqlpyPool(self, kwargs)
        self.pools.append(built)
        return built

    def sql(self) -> list[str]:
        return [query for query, _ in self.statements]


class FakePsqlpyTransaction:
    """One open transaction: the same statements, on the connection that holds it."""

    def __init__(self, server: FakePsqlpyServer) -> None:
        self._server = server

    async def execute(self, query: str, params: Sequence[object] | None = None) -> None:
        await self._server.stall(query)
        self._server.run(query, params)

    async def fetch(self, query: str, params: Sequence[object] | None = None) -> FakePsqlpyResult:
        await self._server.stall(query)
        return FakePsqlpyResult(self._server.run(query, params))

    async def execute_many(self, query: str, params: Sequence[Sequence[object]] | None = None) -> None:
        _ = [self._server.run(query, each) for each in params or ()]


class FakePsqlpyConnection(FakePsqlpyTransaction):
    """A pooled connection: statements, and a transaction scope that commits on a clean exit."""

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[FakePsqlpyTransaction]:
        self._server.transactions.append("begin")
        try:
            yield FakePsqlpyTransaction(self._server)
        except BaseException:
            self._server.transactions.append("rollback")
            raise
        self._server.transactions.append("commit")


class FakePsqlpyPool:
    """`ConnectionPool`: connections handed out in a scope, closed once."""

    def __init__(self, server: FakePsqlpyServer, kwargs: dict[str, Any]) -> None:
        self._server = server
        self.kwargs = kwargs
        self.closed = False

    @asynccontextmanager
    async def acquire(self) -> AsyncGenerator[FakePsqlpyConnection]:
        if self._server.refuse is not None:
            raise self._server.refuse
        self._server.held += 1
        try:
            yield FakePsqlpyConnection(self._server)
        finally:
            self._server.held -= 1

    def close(self) -> None:
        self.closed = True
