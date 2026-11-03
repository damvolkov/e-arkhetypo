"""providers/drivers/database/asyncpg: the SQL edge over asyncpg, and the pool PgQueuer rides.

A pooled client behind `DatabasePort` and `ListenPort`, the twin of the psqlpy driver call for call.

Every connection of the pool is born with psqlpy's shapes: `json`/`jsonb` in and out as Python values (text in is
taken as JSON already, as asyncpg itself takes it), `uuid` out as text; a `Vector` travels as pgvector's text form
(`[1.0,2.0]`, each component through `float`: numpy 2's `repr` is `np.float32(1.0)`), the server's input function
parsing it. A statement always goes through the extended protocol, as psqlpy prepares: one statement, and a
comment-only one is no error; `script` is the simple protocol, several statements without parameters. A transaction
pins one connection for its whole scope, a connection scope pins one with each statement its own commit. LISTEN rides
one connection of the pool held for it, taken with the first channel. asyncpg's errors carry the server's SQLSTATE and
constraint: `DatabaseError` keeps both. `provision` creates the database its DSN names when missing, on the server's
maintenance database; a twin creating it at the same moment is no error. Both Postgres drivers are first-class and the
project picks one at its root; PgQueuer rides either through the ports."""

import json
from contextlib import asynccontextmanager, contextmanager
from typing import TYPE_CHECKING, Any, ClassVar, Final, Self
from urllib.parse import urlsplit

import anyio
import asyncpg

from e_infra.infra.errors import DatabaseError, ProviderError
from e_infra.infra.logger import logger
from e_infra.infra.settings import settings as st
from e_infra.ports.database import Row, Vector
from e_infra.ports.provider import Isolation, Locality, ProviderSpec, Workload

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable, Coroutine, Generator, Sequence
    from contextlib import AbstractAsyncContextManager

    from e_infra.infra.config.providers.drivers.database.asyncpg import AsyncpgSettings
    from e_infra.ports.database import Notify, QueryPort

### the errors that are the driver's own, not the caller's: the server's refusal, a closed connection, the network, a
### command past its timeout.
WIRE: Final[tuple[type[BaseException], ...]] = (asyncpg.PostgresError, asyncpg.InterfaceError, OSError, TimeoutError)
### every Postgres server has it: where a database that does not exist yet is created from.
MAINTENANCE: Final[str] = "postgres"
FOUND: Final[str] = "SELECT 1 FROM pg_database WHERE datname = $1"


##### STATEMENTS #####
class AsyncpgStatements:
    """One held connection — or one inside an open transaction — as a `QueryPort`: every call on it; a nested scope is
    itself. Owns the translation both ways: `Vector` as pgvector's text, asyncpg's error raised as `DatabaseError`."""

    __slots__ = ("_on",)

    def __init__(self, on: asyncpg.Connection) -> None:
        self._on = on

    ##### PRIVATE #####

    @staticmethod
    def _common_error(error: BaseException) -> DatabaseError:
        """asyncpg's error as the tree's: its message, the server's SQLSTATE and constraint when it named them."""
        return DatabaseError(
            str(error) or type(error).__name__,
            sqlstate=getattr(error, "sqlstate", None),
            constraint_name=getattr(error, "constraint_name", None),
        )

    @staticmethod
    @contextmanager
    def _common_guard() -> Generator[None]:
        """asyncpg's own errors, and the network's, as the tree's `DatabaseError`."""
        try:
            yield
        except WIRE as error:
            logger.error("asyncpg failed", error=str(error) or type(error).__name__)
            raise AsyncpgStatements._common_error(error) from error

    @staticmethod
    def _common_params(params: Sequence[object]) -> list[object]:
        """Parameters as asyncpg takes them: a `Vector` as pgvector's text form."""
        return [
            f"[{','.join(str(float(each)) for each in value)}]" if isinstance(value, Vector) else value
            for value in params
        ]

    @classmethod
    async def _common_call[T](cls, call: Coroutine[Any, Any, T]) -> T:
        """One driver call, its refusal a `DatabaseError`."""
        with cls._common_guard():
            return await call

    @staticmethod
    def _common_json(value: object) -> str:
        """A JSON parameter: a Python value encoded; text passed as the JSON it already is — asyncpg's own contract,
        which the libraries riding this driver (PgQueuer) were written against."""
        return value if isinstance(value, str) else json.dumps(value)

    @staticmethod
    async def _common_born(connection: asyncpg.Connection) -> None:
        """A new connection, given psqlpy's shapes: JSON as Python values, UUIDs as text."""
        _ = [
            await connection.set_type_codec(
                kind, encoder=AsyncpgStatements._common_json, decoder=json.loads, schema="pg_catalog"
            )
            for kind in ("json", "jsonb")
        ]
        await connection.set_type_codec("uuid", encoder=str, decoder=str, schema="pg_catalog", format="text")

    @asynccontextmanager
    async def _common_self(self) -> AsyncGenerator[Self]:
        yield self

    ############################################################

    ##### PUBLIC #####

    async def execute(self, query: str, params: Sequence[object] = ()) -> None:
        ### always the extended protocol, as psqlpy prepares: one statement, and a comment-only one is no error.
        _ = await self._common_call(self._on.fetch(query, *self._common_params(params)))

    async def fetch(self, query: str, params: Sequence[object] = ()) -> list[Row]:
        return [dict(record) for record in await self._common_call(self._on.fetch(query, *self._common_params(params)))]

    async def row(self, query: str, params: Sequence[object] = ()) -> Row | None:
        return next(iter(await self.fetch(query, params)), None)

    async def many(self, query: str, params: Sequence[Sequence[object]]) -> None:
        await self._common_call(self._on.executemany(query, [self._common_params(each) for each in params]))

    async def script(self, statements: str) -> None:
        _ = await self._common_call(self._on.execute(statements))

    def transaction(self) -> AbstractAsyncContextManager[Self]:
        return self._common_self()

    def connection(self) -> AbstractAsyncContextManager[Self]:
        return self._common_self()


##### DRIVER #####
class AsyncpgDriver:
    """An asyncpg connection pool behind `DatabasePort` and `ListenPort`."""

    spec: ClassVar[ProviderSpec] = ProviderSpec(
        "asyncpg", Locality.REMOTE, Workload.IO_BOUND, Isolation.LOOP, pooled=True
    )

    __slots__ = ("_channels", "_conf", "_fanouts", "_listener", "_pool")

    def __init__(self, settings: AsyncpgSettings | None = None) -> None:
        ### the default is read on call, not at import: the settings singleton stays lazy.
        self._conf = st.providers.drivers.database.asyncpg if settings is None else settings
        self._pool: asyncpg.Pool | None = None
        self._listener: asyncpg.pool.PoolConnectionProxy | None = None
        self._channels: dict[str, list[Notify]] = {}
        ### asyncpg removes a listener by identity: each channel's one fan-out, kept to remove it.
        self._fanouts: dict[str, Callable[[object, object, object, object], None]] = {}

    ##### PRIVATE #####

    async def _provision_create(self, connection: asyncpg.Connection, name: str) -> bool:
        """Create the database unless it exists; False when it does, or when a twin created it first."""
        try:
            match await connection.fetch(FOUND, name):
                case []:
                    ### CREATE DATABASE takes no parameters: the name is quoted as an identifier, quotes doubled.
                    await connection.execute(f'CREATE DATABASE "{name.replace('"', '""')}"')
                    logger.info("asyncpg database created", database=name)
                    return True
                case _:
                    return False
        except asyncpg.PostgresError:
            return await self._provision_twin(connection, name)

    @staticmethod
    async def _provision_twin(connection: asyncpg.Connection, name: str) -> bool:
        """After a failed create: the database exists — a twin won the race — or the failure was real."""
        match await connection.fetch(FOUND, name):
            case []:
                msg = f"database {name!r} could not be created"
                raise DatabaseError(msg)
            case _:
                return False

    def _common_pool(self) -> asyncpg.Pool:
        match self._pool:
            case None:
                msg = "AsyncpgDriver is not open: the lifespan opens it, callers never do"
                raise DatabaseError(msg)
            case pool:
                return pool

    @asynccontextmanager
    async def _common_held(self, transactional: bool) -> AsyncGenerator[QueryPort]:  # noqa: FBT001 — two scopes, one body
        with AsyncpgStatements._common_guard():
            async with self._common_pool().acquire() as connection:
                match transactional:
                    case True:
                        async with connection.transaction():
                            yield AsyncpgStatements(connection)
                    case _:
                        yield AsyncpgStatements(connection)

    async def _listen_started(self) -> asyncpg.pool.PoolConnectionProxy:
        """The connection LISTEN holds, taken with the first channel."""
        match self._listener:
            case None:
                self._listener = await AsyncpgStatements._common_call(self._common_pool().acquire())
                return self._listener
            case listener:
                return listener

    def _listen_fanout(self, channel: str) -> Callable[[object, object, object, object], None]:
        def fanout(_connection: object, _process: object, _channel: object, payload: object) -> None:
            _ = [callback(str(payload)) for callback in tuple(self._channels.get(channel, ()))]

        return self._fanouts.setdefault(channel, fanout)

    ############################################################

    ##### PUBLIC #####

    async def __aenter__(self) -> Self:
        timeout = self._conf.timeout.total_seconds()
        try:
            with anyio.fail_after(timeout), AsyncpgStatements._common_guard():
                self._pool = self._pool or await asyncpg.create_pool(
                    self._conf.dsn.get_secret_value(),
                    min_size=self._conf.pool_min,
                    max_size=self._conf.pool,
                    command_timeout=timeout,
                    timeout=timeout,
                    init=AsyncpgStatements._common_born,
                )
        except TimeoutError as error:
            msg = f"asyncpg open timed out after {self._conf.timeout}"
            logger.error("asyncpg open timed out", timeout=str(self._conf.timeout))
            raise DatabaseError(msg) from error
        logger.info("asyncpg opened", pool=self._conf.pool)
        return self

    async def __aexit__(self, *exc: object) -> None:
        listener, pool = self._listener, self._pool
        self._listener, self._pool, self._channels, self._fanouts = None, None, {}, {}
        match pool:
            case None:
                return
            case _:
                try:
                    with anyio.fail_after(self._conf.timeout.total_seconds()):
                        _ = listener and await pool.release(listener)
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
            raise
        return True

    async def provision(self) -> bool:
        """Create the database the DSN names when missing; whether this call created it."""
        url = urlsplit(self._conf.dsn.get_secret_value())
        name = url.path.removeprefix("/")
        try:
            admin = await asyncpg.connect(
                url._replace(path=f"/{MAINTENANCE}").geturl(), timeout=self._conf.timeout.total_seconds()
            )
        except WIRE as error:
            msg = f"database {name!r} unreachable: {error}"
            logger.error("asyncpg provision failed", database=name, error=str(error))
            raise DatabaseError(msg) from error
        try:
            return await self._provision_create(admin, name)
        finally:
            await admin.close()

    async def execute(self, query: str, params: Sequence[object] = ()) -> None:
        logger.debug("asyncpg execute", params=len(params))
        async with self.connection() as held:
            await held.execute(query, params)

    async def fetch(self, query: str, params: Sequence[object] = ()) -> list[Row]:
        logger.debug("asyncpg fetch", params=len(params))
        async with self.connection() as held:
            return await held.fetch(query, params)

    async def row(self, query: str, params: Sequence[object] = ()) -> Row | None:
        return next(iter(await self.fetch(query, params)), None)

    async def many(self, query: str, params: Sequence[Sequence[object]]) -> None:
        logger.debug("asyncpg many", sets=len(params))
        async with self.connection() as held:
            await held.many(query, params)

    async def script(self, statements: str) -> None:
        logger.debug("asyncpg script")
        async with self.connection() as held:
            await held.script(statements)

    def transaction(self) -> AbstractAsyncContextManager[QueryPort]:
        logger.debug("asyncpg transaction")
        return self._common_held(transactional=True)

    def connection(self) -> AbstractAsyncContextManager[QueryPort]:
        return self._common_held(transactional=False)

    async def listen(self, channel: str, callback: Notify) -> None:
        listener = await self._listen_started()
        held = self._channels.setdefault(channel, [])
        held.append(callback)
        _ = len(held) == 1 and await AsyncpgStatements._common_call(
            listener.add_listener(channel, self._listen_fanout(channel))
        )

    async def unlisten(self, channel: str, callback: Notify) -> None:
        held = self._channels.get(channel, [])
        _ = callback in held and held.remove(callback)
        ### the channel is released with its last callback, once: a repeated unlisten finds it gone.
        match (held, self._listener, self._fanouts.get(channel)):
            case ([], listener, fanout) if listener is not None and fanout is not None:
                del self._channels[channel], self._fanouts[channel]
                await AsyncpgStatements._common_call(listener.remove_listener(channel, fanout))
            case _:
                pass
