"""providers/drivers/database/psqlpy: the SQL edge over psqlpy — a Rust (tokio-postgres) pool, pgvector bound natively.

Rows come back as dicts; `Vector` parameters bind as pgvector values (a plain list would bind as an array and
the driver panics on it). One pool per process; a transaction pins one connection for its whole scope. Statement
text is the caller's: this driver knows no schema. `provision` creates the database its DSN names when missing, on
the server's maintenance database (CREATE DATABASE runs outside any transaction); a twin creating it at the same
moment — two workers booting — is no error, it was just not this one that created it. psqlpy's own errors are
`DatabaseError` from here up."""

from contextlib import asynccontextmanager, contextmanager
from typing import TYPE_CHECKING, ClassVar, Final, Self
from urllib.parse import urlsplit

from psqlpy import Connection, ConnectionPool, Transaction
from psqlpy.exceptions import Error as PsqlError
from psqlpy.extra_types import PgVector

from e_infra.infra.errors import DatabaseError, ProviderError
from e_infra.infra.settings import settings as st
from e_infra.ports.database import Row, Vector
from e_infra.ports.provider import Isolation, Locality, ProviderSpec, Workload

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator, Sequence
    from contextlib import AbstractAsyncContextManager

    from e_infra.infra.config.postgres import PostgresSettings
    from e_infra.ports.database import QueryPort

### psqlpy refuses a pool of one connection.
FLOOR: Final[int] = 2
### every Postgres server has it: where a database that does not exist yet is created from.
MAINTENANCE: Final[str] = "postgres"
FOUND: Final[str] = "SELECT 1 FROM pg_database WHERE datname = $1"


##### DRIVER #####
class PsqlpyDriver:
    """A psqlpy connection pool behind `DatabasePort`."""

    spec: ClassVar[ProviderSpec] = ProviderSpec(
        "psqlpy", Locality.REMOTE, Workload.IO_BOUND, Isolation.LOOP, pooled=True
    )

    __slots__ = ("_conf", "_pool")

    def __init__(self, settings: PostgresSettings | None = None) -> None:
        ### the default is read on call, not at import: the settings singleton stays lazy.
        self._conf = st.postgres if settings is None else settings
        self._pool: ConnectionPool | None = None

    ##### PRIVATE #####

    @staticmethod
    @contextmanager
    def _common_guard() -> Generator[None]:
        """psqlpy's own error, as the tree's `DatabaseError`."""
        try:
            yield
        except PsqlError as error:
            raise DatabaseError(str(error)) from error

    @staticmethod
    def _common_params(params: Sequence[object]) -> list[object]:
        """Parameters as psqlpy takes them: a `Vector` as a pgvector value."""
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

    ############################################################

    ##### PUBLIC #####

    async def __aenter__(self) -> Self:
        self._pool = self._pool or ConnectionPool(
            dsn=self._conf.dsn.get_secret_value(),
            max_db_pool_size=max(self._conf.pool, FLOOR),
            connect_timeout_sec=int(self._conf.timeout.total_seconds()),
        )
        return self

    async def __aexit__(self, *exc: object) -> None:
        match self._pool:
            case None:
                pass
            case pool:
                pool.close()
                self._pool = None

    async def health(self) -> bool:
        """One trivial query on a pooled connection."""
        try:
            await self.fetch("SELECT 1")
        except ProviderError:
            return False
        return True

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
            raise DatabaseError(msg) from error
        finally:
            admin.close()

    async def execute(self, query: str, params: Sequence[object] = ()) -> None:
        with PsqlpyDriver._common_guard():
            async with self._common_pool().acquire() as connection:
                await connection.execute(query, PsqlpyDriver._common_params(params))

    async def fetch(self, query: str, params: Sequence[object] = ()) -> list[Row]:
        with PsqlpyDriver._common_guard():
            async with self._common_pool().acquire() as connection:
                return (await connection.fetch(query, PsqlpyDriver._common_params(params))).result()

    async def row(self, query: str, params: Sequence[object] = ()) -> Row | None:
        return next(iter(await self.fetch(query, params)), None)

    async def many(self, query: str, params: Sequence[Sequence[object]]) -> None:
        with PsqlpyDriver._common_guard():
            async with self._common_pool().acquire() as connection:
                await connection.execute_many(query, [PsqlpyDriver._common_params(each) for each in params])

    def transaction(self) -> AbstractAsyncContextManager[QueryPort]:
        return self._transaction_scope()

    @asynccontextmanager
    async def _transaction_scope(self) -> AsyncGenerator[QueryPort]:
        with PsqlpyDriver._common_guard():
            async with self._common_pool().acquire() as connection, connection.transaction() as transaction:
                yield PsqlpyTransaction(connection, transaction)


class PsqlpyTransaction:
    """One open transaction as a `QueryPort`: every call on its connection; nested `transaction()` is itself."""

    __slots__ = ("_connection", "_transaction")

    def __init__(self, connection: Connection, transaction: Transaction) -> None:
        self._connection = connection
        self._transaction = transaction

    async def execute(self, query: str, params: Sequence[object] = ()) -> None:
        with PsqlpyDriver._common_guard():
            await self._transaction.execute(query, PsqlpyDriver._common_params(params))

    async def fetch(self, query: str, params: Sequence[object] = ()) -> list[Row]:
        with PsqlpyDriver._common_guard():
            return (await self._transaction.fetch(query, PsqlpyDriver._common_params(params))).result()

    async def row(self, query: str, params: Sequence[object] = ()) -> Row | None:
        return next(iter(await self.fetch(query, params)), None)

    async def many(self, query: str, params: Sequence[Sequence[object]]) -> None:
        with PsqlpyDriver._common_guard():
            await self._transaction.execute_many(query, [PsqlpyDriver._common_params(each) for each in params])

    def transaction(self) -> AbstractAsyncContextManager[Self]:
        return self._transaction_self()

    @asynccontextmanager
    async def _transaction_self(self) -> AsyncGenerator[Self]:
        yield self
