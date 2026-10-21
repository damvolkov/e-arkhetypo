"""adapters/sqlite: StoreAdapter over aiosqlite (stdlib sqlite3 is sync-only on 3.14) — one kv table."""

from typing import TYPE_CHECKING, ClassVar

import aiosqlite
import anyio

from e_core.adapters.base import StoreAdapter
from e_core.core.settings import settings as st

KV_SCHEMA: str = "CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value BLOB NOT NULL)"

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from e_core.core.settings.db import DbSettings


##### TYPES #####
class SQLiteAdapter(StoreAdapter):
    """Same KV contract as redis, backed by one embedded database."""

    name: ClassVar[str] = "sqlite"

    def __init__(self, settings: DbSettings | None = None) -> None:
        ### the default is read on call, not at import: the settings singleton stays lazy.
        self._path = (st.db if settings is None else settings).db_path
        self._db: aiosqlite.Connection | None = None

    ##### PRIVATE METHODS #####

    def _common_connected(self) -> aiosqlite.Connection:
        match self._db:
            case None:
                msg = "SQLiteAdapter not connected: the lifespan opens it, handlers never do"
                raise RuntimeError(msg)
            case db:
                return db

    @staticmethod
    def _connect_mkdir(path: Path) -> None:
        """Build the whole parent chain of the database file — sync disk I/O, kept off the loop by connect()."""
        path.parent.mkdir(parents=True, exist_ok=True)

    ############################################################

    ##### PUBLIC #####

    async def connect(self) -> None:
        ### mkdir is blocking filesystem work inside a coroutine: off-thread or it freezes every task.
        await anyio.to_thread.run_sync(self._connect_mkdir, self._path)
        self._db = await aiosqlite.connect(self._path)
        await self._db.executescript(KV_SCHEMA)
        await self._db.commit()

    async def close(self) -> None:
        match self._db:
            case None:
                return
            case db:
                await db.close()
                self._db = None

    async def get(self, key: str) -> bytes | None:
        async with self._common_connected().execute("SELECT value FROM kv WHERE key = ?", (key,)) as cursor:
            row = await cursor.fetchone()
        return None if row is None else row[0]

    async def set(self, key: str, value: bytes) -> None:
        await self._common_connected().execute("INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)", (key, value))
        await self._common_connected().commit()

    async def delete(self, key: str) -> None:
        await self._common_connected().execute("DELETE FROM kv WHERE key = ?", (key,))
        await self._common_connected().commit()

    async def keys(self, prefix: str = "") -> AsyncIterator[str]:
        """Keys starting with `prefix`, streamed row by row in key order — no fetchall, no materialization."""
        async with self._common_connected().execute(
            "SELECT key FROM kv WHERE key LIKE ? ORDER BY key",
            (f"{prefix}%",),
        ) as cursor:
            async for row in cursor:
                yield row[0]
