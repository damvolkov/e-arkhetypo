"""providers/drivers/database/asyncpg: the SQL edge over asyncpg — a pooled client, and the pool PgQueuer rides.

Same contract as the psqlpy driver, `DatabasePort`: `$n` parameters, rows as dicts, a transaction scope pinning one
connection, errors as `DatabaseError`. One pool per process, a connection taken per operation and never kept; a `Vector`
binds as pgvector's text form (asyncpg ships no codec for the extension). Both Postgres drivers are first-class and the
project picks one at its root. What a library that owns its client needs — PgQueuer's `Queries` run on an asyncpg
connection, and its LISTEN and managers each hold one for as long as they live — is on this class and nowhere in the
ports: `pool` is the pool, `connection` a dedicated connection opened and closed within a block, `guard` the border
that turns asyncpg's errors into `DatabaseError`."""

from contextlib import asynccontextmanager, contextmanager, suppress
from typing import TYPE_CHECKING, ClassVar, Self

import anyio
import asyncpg

from e_infra.infra.errors import DatabaseError, ProviderError
from e_infra.infra.logger import logger
from e_infra.infra.settings import settings as st
from e_infra.ports.database import Row, Vector
from e_infra.ports.provider import Isolation, Locality, ProviderSpec, Workload

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator, Sequence
    from contextlib import AbstractAsyncContextManager

    from e_infra.infra.config.providers.drivers.database.asyncpg import AsyncpgSettings
    from e_infra.ports.database import QueryPort

WIRE = (asyncpg.PostgresError, asyncpg.InterfaceError, OSError)


##### DRIVER #####
class AsyncpgDriver:
    """An asyncpg connection pool behind `DatabasePort`."""

    spec: ClassVar[ProviderSpec] = ProviderSpec(
        "asyncpg", Locality.REMOTE, Workload.IO_BOUND, Isolation.LOOP, pooled=True
    )

    __slots__ = ("_conf", "_pool")

    def __init__(self, settings: AsyncpgSettings | None = None) -> None:
        ### the default is read on call, not at import: the settings singleton stays lazy.
        self._conf = st.providers.drivers.database.asyncpg if settings is None else settings
        self._pool: asyncpg.Pool | None = None

    ##### PRIVATE #####

    @staticmethod
    def _common_params(params: Sequence[object]) -> list[object]:
        """Parameters as asyncpg takes them: a `Vector` as pgvector's text form."""
        return [f"[{','.join(map(repr, value))}]" if isinstance(value, Vector) else value for value in params]

    ############################################################

    ##### PUBLIC #####

    @property
    def pool(self) -> asyncpg.Pool:
        """The pool, for a library that runs on asyncpg itself; closed, a `DatabaseError`."""
        match self._pool:
            case None:
                msg = "AsyncpgDriver is not open: the lifespan opens it, callers never do"
                raise DatabaseError(msg)
            case pool:
                return pool

    @staticmethod
    @contextmanager
    def guard() -> Generator[None]:
        """asyncpg's own errors, and the network's, as the tree's `DatabaseError`."""
        try:
            yield
        except WIRE as error:
            logger.error("asyncpg failed", error=str(error) or type(error).__name__)
            raise DatabaseError(str(error) or type(error).__name__) from error

    @asynccontextmanager
    async def connection(self) -> AsyncGenerator[asyncpg.Connection]:
        """A connection of its own, outside the pool, closed on exit — a LISTEN or a manager lives as long as it."""
        timeout = self._conf.timeout.total_seconds()
        with self.guard():
            connection = await asyncpg.connect(self._conf.dsn.get_secret_value(), timeout=timeout)
        logger.debug("asyncpg dedicated connection opened")
        try:
            yield connection
        finally:
            with anyio.CancelScope(shield=True), suppress(Exception):
                await connection.close(timeout=timeout)
            logger.debug("asyncpg dedicated connection closed")

    async def __aenter__(self) -> Self:
        timeout = self._conf.timeout.total_seconds()
        try:
            with anyio.fail_after(timeout), self.guard():
                self._pool = self._pool or await asyncpg.create_pool(
                    self._conf.dsn.get_secret_value(),
                    min_size=self._conf.pool_min,
                    max_size=self._conf.pool,
                    command_timeout=timeout,
                    timeout=timeout,
                )
        except TimeoutError as error:
            msg = f"asyncpg open timed out after {self._conf.timeout}"
            logger.error("asyncpg open timed out", timeout=str(self._conf.timeout))
            raise DatabaseError(msg) from error
        logger.info("asyncpg opened", pool=self._conf.pool)
        return self

    async def __aexit__(self, *exc: object) -> None:
        pool, self._pool = self._pool, None
        match pool:
            case None:
                return
            case _:
                try:
                    with anyio.fail_after(self._conf.timeout.total_seconds()):
                        await pool.close()
                except TimeoutError as error:
                    pool.terminate()
                    msg = f"asyncpg close timed out after {self._conf.timeout}"
                    logger.error("asyncpg close timed out", timeout=str(self._conf.timeout))
                    raise DatabaseError(msg) from error
                logger.info("asyncpg closed")

    async def health(self) -> bool:
        """One trivial query on a pooled connection."""
        try:
            await self.fetch("SELECT 1")
        except ProviderError as error:
            logger.warning("asyncpg unhealthy", error=str(error))
            return False
        return True

    async def execute(self, query: str, params: Sequence[object] = ()) -> None:
        logger.debug("asyncpg execute", params=len(params))
        with self.guard():
            await self.pool.execute(query, *self._common_params(params))

    async def fetch(self, query: str, params: Sequence[object] = ()) -> list[Row]:
        logger.debug("asyncpg fetch", params=len(params))
        with self.guard():
            return [dict(record) for record in await self.pool.fetch(query, *self._common_params(params))]

    async def row(self, query: str, params: Sequence[object] = ()) -> Row | None:
        return next(iter(await self.fetch(query, params)), None)

    async def many(self, query: str, params: Sequence[Sequence[object]]) -> None:
        logger.debug("asyncpg many", sets=len(params))
        with self.guard():
            await self.pool.executemany(query, [self._common_params(each) for each in params])

    def transaction(self) -> AbstractAsyncContextManager[QueryPort]:
        return self._transaction_scope()

    @asynccontextmanager
    async def _transaction_scope(self) -> AsyncGenerator[QueryPort]:
        logger.debug("asyncpg transaction")
        with self.guard():
            async with self.pool.acquire() as connection, connection.transaction():
                yield AsyncpgTransaction(connection)


class AsyncpgTransaction:
    """One open transaction as a `QueryPort`: every call on its connection; nested `transaction()` is itself."""

    __slots__ = ("_connection",)

    def __init__(self, connection: asyncpg.Connection) -> None:
        self._connection = connection

    async def execute(self, query: str, params: Sequence[object] = ()) -> None:
        with AsyncpgDriver.guard():
            await self._connection.execute(query, *AsyncpgDriver._common_params(params))

    async def fetch(self, query: str, params: Sequence[object] = ()) -> list[Row]:
        with AsyncpgDriver.guard():
            return [
                dict(record) for record in await self._connection.fetch(query, *AsyncpgDriver._common_params(params))
            ]

    async def row(self, query: str, params: Sequence[object] = ()) -> Row | None:
        return next(iter(await self.fetch(query, params)), None)

    async def many(self, query: str, params: Sequence[Sequence[object]]) -> None:
        with AsyncpgDriver.guard():
            await self._connection.executemany(query, [AsyncpgDriver._common_params(each) for each in params])

    def transaction(self) -> AbstractAsyncContextManager[Self]:
        return self._transaction_self()

    @asynccontextmanager
    async def _transaction_self(self) -> AsyncGenerator[Self]:
        yield self
