"""adapters/postgres: the SQL edge over psqlpy — a Rust (tokio-postgres) pool, pgvector bound natively.

Rows come back as dicts; `Vector` parameters bind as pgvector values (a plain list would bind as an array and
the driver panics on it). One pool per app; a transaction pins one connection for its whole scope. Statement
text is the caller's: this adapter knows no schema. `provision` creates the database its DSN names when missing, on
the server's maintenance database (CREATE DATABASE runs outside any transaction); a twin creating it at the same
moment — two workers booting — is no error, it was just not this one that created it."""

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, ClassVar, Final, Self
from urllib.parse import urlsplit

from psqlpy import Connection, ConnectionPool, Transaction
from psqlpy.exceptions import Error as PsqlError
from psqlpy.extra_types import PgVector

from e_core.adapters.base import BaseAdapter
from e_core.adapters.ports import Row, SqlPort, Vector
from e_core.core.settings import settings as st

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Sequence
    from contextlib import AbstractAsyncContextManager

    from e_core.core.settings.postgres import PostgresSettings

### psqlpy refuses a pool of one connection.
FLOOR: Final[int] = 2
### every Postgres server has it: where a database that does not exist yet is created from.
MAINTENANCE: Final[str] = "postgres"
FOUND: Final[str] = "SELECT 1 FROM pg_database WHERE datname = $1"


class PostgresError(RuntimeError):
    """The adapter used before `connect` or after `close`, or a database it could not reach or create."""


class PostgresAdapter(BaseAdapter):
    """A psqlpy connection pool behind `SqlPort`."""

    name: ClassVar[str] = "postgres"

    __slots__ = ("_conf", "_pool")

    def __init__(self, settings: PostgresSettings | None = None) -> None:
        ### the default is read on call, not at import: the settings singleton stays lazy.
        self._conf = st.postgres if settings is None else settings
        self._pool: ConnectionPool | None = None

    ##### PRIVATE #####

    @staticmethod
    def _common_params(params: Sequence[object]) -> list[object]:
        return [PgVector(list(value)) if isinstance(value, Vector) else value for value in params]

    async def _provision_create(self, connection: Connection, name: str) -> bool:
        """Create the database unless it exists; False when it does, or when a twin created it first."""
        try:
            match (await connection.fetch(FOUND, [name])).result():
                case []:
                    ### CREATE DATABASE takes no parameters: the name is quoted as an identifier, quotes doubled.
                    await connection.execute(f'CREATE DATABASE "{name.replace('"', '""')}"')
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
                raise PostgresError(msg)
            case _:
                return False

    def _common_pool(self) -> ConnectionPool:
        match self._pool:
            case None:
                msg = "postgres adapter is not connected"
                raise PostgresError(msg)
            case pool:
                return pool

    ############################################################

    ##### PUBLIC #####

    async def connect(self) -> None:
        self._pool = self._pool or ConnectionPool(
            dsn=self._conf.dsn.get_secret_value(),
            max_db_pool_size=max(self._conf.pool, FLOOR),
            connect_timeout_sec=int(self._conf.timeout.total_seconds()),
        )

    async def provision(self) -> bool:
        """Create the database the DSN names when missing; whether this call created it."""
        url = urlsplit(self._conf.dsn.get_secret_value())
        name = url.path.removeprefix("/")
        admin = ConnectionPool(
            dsn=url._replace(path=f"/{MAINTENANCE}").geturl(),
            max_db_pool_size=FLOOR,
            connect_timeout_sec=int(self._conf.timeout.total_seconds()),
        )
        try:
            async with admin.acquire() as connection:
                return await self._provision_create(connection, name)
        except PsqlError as error:
            msg = f"database {name!r} unreachable: {error}"
            raise PostgresError(msg) from error
        finally:
            admin.close()

    async def close(self) -> None:
        match self._pool:
            case None:
                pass
            case pool:
                pool.close()
                self._pool = None

    async def execute(self, query: str, params: Sequence[object] = ()) -> None:
        async with self._common_pool().acquire() as connection:
            await connection.execute(query, self._common_params(params))

    async def fetch(self, query: str, params: Sequence[object] = ()) -> list[Row]:
        async with self._common_pool().acquire() as connection:
            return (await connection.fetch(query, self._common_params(params))).result()

    async def row(self, query: str, params: Sequence[object] = ()) -> Row | None:
        return next(iter(await self.fetch(query, params)), None)

    async def many(self, query: str, params: Sequence[Sequence[object]]) -> None:
        async with self._common_pool().acquire() as connection:
            await connection.execute_many(query, [self._common_params(each) for each in params])

    def transaction(self) -> AbstractAsyncContextManager[SqlPort]:
        return self._transaction_scope()

    @asynccontextmanager
    async def _transaction_scope(self) -> AsyncGenerator[SqlPort]:
        async with self._common_pool().acquire() as connection, connection.transaction() as transaction:
            yield PostgresTransaction(connection, transaction)


class PostgresTransaction:
    """One open transaction as a `SqlPort`: every call on its connection; nested `transaction()` is itself."""

    name: ClassVar[str] = "postgres"

    __slots__ = ("_connection", "_transaction")

    def __init__(self, connection: Connection, transaction: Transaction) -> None:
        self._connection = connection
        self._transaction = transaction

    async def execute(self, query: str, params: Sequence[object] = ()) -> None:
        await self._transaction.execute(query, PostgresAdapter._common_params(params))

    async def fetch(self, query: str, params: Sequence[object] = ()) -> list[Row]:
        return (await self._transaction.fetch(query, PostgresAdapter._common_params(params))).result()

    async def row(self, query: str, params: Sequence[object] = ()) -> Row | None:
        return next(iter(await self.fetch(query, params)), None)

    async def many(self, query: str, params: Sequence[Sequence[object]]) -> None:
        await self._transaction.execute_many(query, [PostgresAdapter._common_params(each) for each in params])

    def transaction(self) -> AbstractAsyncContextManager[SqlPort]:
        return self._transaction_self()

    @asynccontextmanager
    async def _transaction_self(self) -> AsyncGenerator[Self]:
        yield self
