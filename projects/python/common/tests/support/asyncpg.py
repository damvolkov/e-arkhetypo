"""tests/support/asyncpg: an asyncpg pool and connection that hold no database — rows scripted, SQL recorded.

asyncpg has no fake of its own. A `FakeAsyncpgServer` is what the pools and dedicated connections of one test share:
answers by a fragment of the statement, failures by a fragment (the library's own exceptions), every statement run with
its parameters, and the transaction events. The driver is patched to build them: `asyncpg.create_pool` and
`asyncpg.connect` answer `server.create_pool` and `server.connect`. `held` counts pooled connections taken and not
given back, `dedicated` the connections opened outside the pool and not closed."""

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import anyio

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

type Row = dict[str, Any]


@dataclass(slots=True)
class FakeAsyncpgServer:
    """The shared state of every pool and connection built in one test."""

    answers: dict[str, list[Row]] = field(default_factory=dict)
    failures: dict[str, BaseException] = field(default_factory=dict)
    statements: list[tuple[str, tuple[object, ...]]] = field(default_factory=list)
    transactions: list[str] = field(default_factory=list)
    pools: list[FakeAsyncpgPool] = field(default_factory=list)
    connections: list[FakeAsyncpgConnection] = field(default_factory=list)
    refuse: BaseException | None = None
    hang: str = ""
    held: int = 0
    dedicated: int = 0

    async def stall(self, query: str) -> None:
        """A statement that never answers, until its caller is cancelled."""
        _ = self.hang and self.hang in query and await anyio.sleep_forever()

    def run(self, query: str, args: tuple[object, ...]) -> list[Row]:
        """Record the statement, raise the failure scripted for it, else answer the rows scripted for it."""
        self.statements.append((query, args))
        for fragment, failure in self.failures.items():
            if fragment in query:
                raise failure
        return next((rows for fragment, rows in self.answers.items() if fragment in query), [])

    def sql(self) -> list[str]:
        return [query for query, _ in self.statements]

    async def create_pool(self, dsn: str, **kwargs: Any) -> FakeAsyncpgPool:
        """`asyncpg.create_pool`: refused when `refuse` is set, else a pool that remembers how it was asked for."""
        if self.refuse is not None:
            raise self.refuse
        built = FakeAsyncpgPool(self, dsn, kwargs)
        self.pools.append(built)
        return built

    async def connect(self, dsn: str, **kwargs: Any) -> FakeAsyncpgConnection:
        """`asyncpg.connect`: a connection of its own, outside any pool."""
        if self.refuse is not None:
            raise self.refuse
        self.dedicated += 1
        self.connections.append(FakeAsyncpgConnection(self, dedicated=True, dsn=dsn, kwargs=kwargs))
        return self.connections[-1]


class FakeAsyncpgConnection:
    """A connection: statements, a transaction scope, and a close that a dedicated one owes."""

    def __init__(
        self, server: FakeAsyncpgServer, *, dedicated: bool = False, dsn: str = "", kwargs: dict[str, Any] | None = None
    ) -> None:
        self._server = server
        self._dedicated = dedicated
        self.dsn = dsn
        self.kwargs = kwargs or {}
        self.closed = False

    async def execute(self, query: str, *args: object) -> str:
        await self._server.stall(query)
        self._server.run(query, args)
        return "OK"

    async def fetch(self, query: str, *args: object) -> list[Row]:
        await self._server.stall(query)
        return self._server.run(query, args)

    async def fetchrow(self, query: str, *args: object) -> Row | None:
        await self._server.stall(query)
        return next(iter(self._server.run(query, args)), None)

    async def fetchval(self, query: str, *args: object) -> object:
        await self._server.stall(query)
        return next(iter(next(iter(self._server.run(query, args)), {}).values()), None)

    async def executemany(self, query: str, args: list[tuple[object, ...]]) -> None:
        _ = [self._server.run(query, tuple(each)) for each in args]

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[None]:
        self._server.transactions.append("begin")
        try:
            yield
        except BaseException:
            self._server.transactions.append("rollback")
            raise
        self._server.transactions.append("commit")

    async def close(self, *, timeout: float | None = None) -> None:  # noqa: ASYNC109 — asyncpg's own signature
        match (self._dedicated, self.closed):
            case (True, False):
                self._server.dedicated -= 1
            case _:
                pass
        self.closed = True


class FakeAsyncpgPool:
    """`asyncpg.Pool`: a call takes a connection and gives it back, as the real pool does."""

    def __init__(self, server: FakeAsyncpgServer, dsn: str, kwargs: dict[str, Any]) -> None:
        self._server = server
        self.dsn = dsn
        self.kwargs = kwargs
        self.closed = False
        self.terminated = False

    @asynccontextmanager
    async def acquire(self) -> AsyncGenerator[FakeAsyncpgConnection]:
        self._server.held += 1
        try:
            yield FakeAsyncpgConnection(self._server)
        finally:
            self._server.held -= 1

    async def execute(self, query: str, *args: object) -> str:
        async with self.acquire() as connection:
            return await connection.execute(query, *args)

    async def fetch(self, query: str, *args: object) -> list[Row]:
        async with self.acquire() as connection:
            return await connection.fetch(query, *args)

    async def fetchrow(self, query: str, *args: object) -> Row | None:
        async with self.acquire() as connection:
            return await connection.fetchrow(query, *args)

    async def fetchval(self, query: str, *args: object) -> object:
        async with self.acquire() as connection:
            return await connection.fetchval(query, *args)

    async def executemany(self, query: str, args: list[tuple[object, ...]]) -> None:
        async with self.acquire() as connection:
            await connection.executemany(query, args)

    async def close(self) -> None:
        self.closed = True

    def terminate(self) -> None:
        self.terminated = True
