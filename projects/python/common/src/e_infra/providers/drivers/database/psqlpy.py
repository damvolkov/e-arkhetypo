"""providers/drivers/database/psqlpy: the SQL edge over psqlpy, a Rust (tokio-postgres) pool.

Behind `DatabasePort` and `ListenPort`, the twin of the asyncpg driver call for call, pgvector bound natively.

Rows come back as dicts; `Vector` parameters bind as pgvector values (a plain list would bind as an array and
the driver panics on it). One pool per process; a transaction pins one connection for its whole scope, a connection
scope pins one with each statement its own commit. LISTEN rides psqlpy's listener, a connection of its own; psqlpy only
listens for sure on the channels it holds when it starts, so a new channel starts a new listener holding them all and
stops the old one — each listener a generation, only the newest delivering. One callback per channel fans each payload
out to every callback listening there; unlistening drops a callback, the channel stays held until close. Statement
text is the caller's: this driver knows no schema. psqlpy's errors carry the server's message only, no SQLSTATE: a
unique violation is read off the message (the server's English, `lc_messages` C or en) — the one state a caller
branches on. `provision` creates the database its DSN names when missing, on the server's maintenance database
(CREATE DATABASE runs outside any transaction); a twin creating it at the same moment — two workers booting — is no
error, it was just not this one that created it. psqlpy's own errors are `DatabaseError` from here up."""

import re
from contextlib import asynccontextmanager, contextmanager
from typing import TYPE_CHECKING, Any, ClassVar, Final, Self
from urllib.parse import urlsplit

from psqlpy import Connection, ConnectionPool, Listener, Transaction
from psqlpy.exceptions import Error as PsqlError
from psqlpy.extra_types import PgVector

from e_infra.infra.errors import DatabaseError, ProviderError
from e_infra.infra.logger import logger
from e_infra.ports.database import Row, Vector
from e_infra.ports.provider import Isolation, Locality, ProviderSpec, Workload

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable, Coroutine, Generator, Sequence
    from contextlib import AbstractAsyncContextManager
    from datetime import timedelta

    from pydantic import PostgresDsn, Secret

    from e_infra.ports.database import Notify, QueryPort

### psqlpy refuses a pool of one connection.
FLOOR: Final[int] = 2
### every Postgres server has it: where a database that does not exist yet is created from.
MAINTENANCE: Final[str] = "postgres"
FOUND: Final[str] = "SELECT 1 FROM pg_database WHERE datname = $1"
UNIQUE: Final[re.Pattern[str]] = re.compile(r'duplicate key value violates unique constraint "(?P<constraint>[^"]+)"')
UNIQUE_STATE: Final[str] = "23505"


##### STATEMENTS #####
class PsqlpyStatements:
    """One held connection or open transaction as a `QueryPort`: every call on it; a nested scope is itself. Owns the
    translation both ways: `Vector` bound as pgvector, psqlpy's error raised as `DatabaseError`."""

    __slots__ = ("_on",)

    def __init__(self, on: Connection | Transaction) -> None:
        self._on = on

    ##### PRIVATE #####

    @staticmethod
    def _common_error(error: PsqlError) -> DatabaseError:
        """psqlpy's error as the tree's: its message, and the unique violation the message names."""
        message = str(error)
        match UNIQUE.search(message):
            case None:
                return DatabaseError(message)
            case found:
                return DatabaseError(message, sqlstate=UNIQUE_STATE, constraint_name=found["constraint"])

    @staticmethod
    @contextmanager
    def _common_guard() -> Generator[None]:
        """psqlpy's own error, as the tree's `DatabaseError`."""
        try:
            yield
        except PsqlError as error:
            logger.error("psqlpy failed", error=str(error))
            raise PsqlpyStatements._common_error(error) from error

    @staticmethod
    def _common_params(params: Sequence[object]) -> list[object]:
        """Parameters as psqlpy takes them: a `Vector` as a pgvector value."""
        return [PgVector(list(value)) if isinstance(value, Vector) else value for value in params]

    @classmethod
    async def _common_call[T](cls, call: Coroutine[Any, Any, T]) -> T:
        """One driver call, its refusal a `DatabaseError`."""
        with cls._common_guard():
            return await call

    @asynccontextmanager
    async def _common_self(self) -> AsyncGenerator[Self]:
        yield self

    ############################################################

    ##### PUBLIC #####

    async def execute(self, query: str, params: Sequence[object] = ()) -> None:
        await self._common_call(self._on.execute(query, self._common_params(params)))

    async def fetch(self, query: str, params: Sequence[object] = ()) -> list[Row]:
        return (await self._common_call(self._on.fetch(query, self._common_params(params)))).result()

    async def row(self, query: str, params: Sequence[object] = ()) -> Row | None:
        return next(iter(await self.fetch(query, params)), None)

    async def many(self, query: str, params: Sequence[Sequence[object]]) -> None:
        await self._common_call(self._on.execute_many(query, [self._common_params(each) for each in params]))

    async def script(self, statements: str) -> None:
        await self._common_call(self._on.execute_batch(statements))

    def transaction(self) -> AbstractAsyncContextManager[Self]:
        return self._common_self()

    def connection(self) -> AbstractAsyncContextManager[Self]:
        return self._common_self()


##### DRIVER #####
class PsqlpyDriver:
    """A psqlpy connection pool behind `DatabasePort` and `ListenPort`."""

    spec: ClassVar[ProviderSpec] = ProviderSpec(
        "psqlpy", Locality.REMOTE, Workload.IO_BOUND, Isolation.LOOP, pooled=True
    )

    __slots__ = ("_channels", "_dsn", "_generation", "_listener", "_pool", "_size", "_timeout")

    def __init__(self, *, dsn: Secret[PostgresDsn], pool: int, timeout: timedelta) -> None:
        self._dsn, self._size, self._timeout = dsn, pool, timeout
        self._pool: ConnectionPool | None = None
        self._listener: Listener | None = None
        self._channels: dict[str, list[Notify]] = {}
        self._generation = 0

    ##### PRIVATE #####

    async def _provision_create(self, connection: Connection, name: str) -> bool:
        """Create the database unless it exists; False when it does, or when a twin created it first."""
        try:
            match (await connection.fetch(FOUND, [name])).result():
                case []:
                    ### CREATE DATABASE takes no parameters: the name is quoted as an identifier, quotes doubled.
                    await connection.execute(f'CREATE DATABASE "{name.replace('"', '""')}"')
                    logger.info("psqlpy database created", database=name)
                    return True
                case _:
                    return False
        except PsqlError:
            return await self._provision_twin(connection, name)

    @staticmethod
    async def _provision_twin(connection: Connection, name: str) -> bool:
        """After a failed create: the database exists — a twin won the race — or the failure was real."""
        match (await connection.fetch(FOUND, [name])).result():
            case []:
                msg = f"database {name!r} could not be created"
                raise DatabaseError(msg)
            case _:
                return False

    def _common_pool(self) -> ConnectionPool:
        match self._pool:
            case None:
                msg = "PsqlpyDriver is not open: the lifespan opens it, callers never do"
                raise DatabaseError(msg)
            case pool:
                return pool

    @asynccontextmanager
    async def _common_held(self, transactional: bool) -> AsyncGenerator[QueryPort]:  # noqa: FBT001 — two scopes, one body
        with PsqlpyStatements._common_guard():
            async with self._common_pool().acquire() as connection:
                match transactional:
                    case True:
                        async with connection.transaction() as transaction:
                            yield PsqlpyStatements(transaction)
                    case _:
                        yield PsqlpyStatements(connection)

    async def _listen_renewed(self) -> None:
        """A listener holding every channel, started; the one it replaces stopped after it, never before."""
        generation = self._generation + 1
        listener = self._common_pool().listener()
        _ = [
            await PsqlpyStatements._common_call(
                listener.add_callback(channel, self._listen_fanout(channel, generation))
            )
            for channel in self._channels
        ]
        await PsqlpyStatements._common_call(listener.startup())
        listener.listen()
        old, self._listener, self._generation = self._listener, listener, generation
        _ = old and await old.shutdown()
        logger.debug("psqlpy listening", channels=len(self._channels), generation=generation)

    def _listen_fanout(
        self, channel: str, generation: int
    ) -> Callable[[Connection, str, str, int], Coroutine[Any, Any, None]]:
        async def fanout(_connection: Connection, payload: str, _channel: str, _process: int) -> None:
            _ = generation == self._generation and [callback(payload) for callback in tuple(self._channels[channel])]

        return fanout

    ############################################################

    ##### PUBLIC #####

    async def __aenter__(self) -> Self:
        self._pool = self._pool or ConnectionPool(
            dsn=str(self._dsn.get_secret_value()),
            max_db_pool_size=max(self._size, FLOOR),
            connect_timeout_sec=int(self._timeout.total_seconds()),
        )
        logger.info("psqlpy opened", pool=max(self._size, FLOOR))
        return self

    async def __aexit__(self, *exc: object) -> None:
        listener, pool = self._listener, self._pool
        self._listener, self._pool, self._channels = None, None, {}
        _ = listener and await listener.shutdown()
        match pool:
            case None:
                pass
            case _:
                pool.close()
                logger.info("psqlpy closed")

    async def health(self) -> bool:
        """One trivial query on a pooled connection."""
        try:
            await self.fetch("SELECT 1")
        except ProviderError as error:
            logger.warning("psqlpy unhealthy", error=str(error))
            raise
        return True

    async def provision(self) -> bool:
        """Create the database the DSN names when missing; whether this call created it."""
        url = urlsplit(str(self._dsn.get_secret_value()))
        name = url.path.removeprefix("/")
        admin = ConnectionPool(
            dsn=url._replace(path=f"/{MAINTENANCE}").geturl(),
            max_db_pool_size=FLOOR,
            connect_timeout_sec=int(self._timeout.total_seconds()),
        )
        try:
            async with admin.acquire() as connection:
                return await self._provision_create(connection, name)
        except PsqlError as error:
            msg = f"database {name!r} unreachable: {error}"
            logger.error("psqlpy provision failed", database=name, error=str(error))
            raise DatabaseError(msg) from error
        finally:
            admin.close()

    async def execute(self, query: str, params: Sequence[object] = ()) -> None:
        logger.debug("psqlpy execute", params=len(params))
        async with self.connection() as held:
            await held.execute(query, params)

    async def fetch(self, query: str, params: Sequence[object] = ()) -> list[Row]:
        logger.debug("psqlpy fetch", params=len(params))
        async with self.connection() as held:
            return await held.fetch(query, params)

    async def row(self, query: str, params: Sequence[object] = ()) -> Row | None:
        return next(iter(await self.fetch(query, params)), None)

    async def many(self, query: str, params: Sequence[Sequence[object]]) -> None:
        logger.debug("psqlpy many", sets=len(params))
        async with self.connection() as held:
            await held.many(query, params)

    async def script(self, statements: str) -> None:
        logger.debug("psqlpy script")
        async with self.connection() as held:
            await held.script(statements)

    def transaction(self) -> AbstractAsyncContextManager[QueryPort]:
        logger.debug("psqlpy transaction")
        return self._common_held(transactional=True)

    def connection(self) -> AbstractAsyncContextManager[QueryPort]:
        return self._common_held(transactional=False)

    async def listen(self, channel: str, callback: Notify) -> None:
        held = channel in self._channels
        self._channels.setdefault(channel, []).append(callback)
        _ = held or await self._listen_renewed()

    async def unlisten(self, channel: str, callback: Notify) -> None:
        held = self._channels.get(channel, [])
        _ = callback in held and held.remove(callback)
