"""providers/drivers/store/sqlite: a store over aiosqlite (stdlib sqlite3 is sync-only on 3.14) — one kv table in one file."""

from contextlib import contextmanager
from typing import TYPE_CHECKING, ClassVar, Final, Self

import aiosqlite
import anyio

from e_infra.infra.errors import ProviderError, StoreError
from e_infra.infra.settings import settings as st
from e_infra.ports.provider import Isolation, Locality, ProviderSpec, Workload

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Generator
    from pathlib import Path

    from e_infra.infra.config.db import DbSettings

KV_SCHEMA: Final[str] = "CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value BLOB NOT NULL)"


##### TYPES #####
class SqliteDriver:
    """Same KV contract as redis, backed by one embedded database: a file with the semantics of a service."""

    spec: ClassVar[ProviderSpec] = ProviderSpec("sqlite", Locality.FILESYSTEM, Workload.IO_BOUND, Isolation.THREAD)

    def __init__(self, settings: DbSettings | None = None) -> None:
        ### the default is read on call, not at import: the settings singleton stays lazy.
        self._path = (st.db if settings is None else settings).db_path
        self._db: aiosqlite.Connection | None = None

    ##### PRIVATE METHODS #####

    @staticmethod
    @contextmanager
    def _common_guard() -> Generator[None]:
        """aiosqlite's own error, as the tree's `StoreError`."""
        try:
            yield
        except aiosqlite.Error as error:
            raise StoreError(str(error)) from error

    def _common_open(self) -> aiosqlite.Connection:
        match self._db:
            case None:
                msg = "SqliteDriver is not open: the lifespan opens it, handlers never do"
                raise StoreError(msg)
            case db:
                return db

    @staticmethod
    def _enter_mkdir(path: Path) -> None:
        """Build the whole parent chain of the database file — sync disk I/O, kept off the loop by __aenter__."""
        path.parent.mkdir(parents=True, exist_ok=True)

    ############################################################

    ##### PUBLIC #####

    async def __aenter__(self) -> Self:
        ### mkdir is blocking filesystem work inside a coroutine: off-thread or it freezes every task.
        await anyio.to_thread.run_sync(self._enter_mkdir, self._path)
        with self._common_guard():
            self._db = await aiosqlite.connect(self._path)
            await self._db.executescript(KV_SCHEMA)
            await self._db.commit()
        return self

    async def __aexit__(self, *exc: object) -> None:
        match self._db:
            case None:
                return
            case db:
                await db.close()
                self._db = None

    async def health(self) -> bool:
        """One trivial statement on the open file."""
        try:
            with self._common_guard():
                async with self._common_open().execute("SELECT 1") as cursor:
                    await cursor.fetchone()
        except ProviderError:
            return False
        return True

    async def get(self, key: str) -> bytes | None:
        with self._common_guard():
            async with self._common_open().execute("SELECT value FROM kv WHERE key = ?", (key,)) as cursor:
                row = await cursor.fetchone()
        return None if row is None else row[0]

    async def set(self, key: str, value: bytes) -> None:
        with self._common_guard():
            await self._common_open().execute("INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)", (key, value))
            await self._common_open().commit()

    async def delete(self, key: str) -> None:
        with self._common_guard():
            await self._common_open().execute("DELETE FROM kv WHERE key = ?", (key,))
            await self._common_open().commit()

    async def keys(self, prefix: str = "") -> AsyncIterator[str]:
        """Keys starting with `prefix`, streamed row by row in key order — no fetchall, no materialization."""
        with self._common_guard():
            async with self._common_open().execute(
                "SELECT key FROM kv WHERE key LIKE ? ORDER BY key",
                (f"{prefix}%",),
            ) as cursor:
                async for row in cursor:
                    yield row[0]
