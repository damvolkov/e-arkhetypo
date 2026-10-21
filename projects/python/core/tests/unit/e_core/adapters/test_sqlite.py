"""tests/unit/e_core/adapters/sqlite: the full KV lifecycle on one embedded file."""

from typing import TYPE_CHECKING

import pytest

from e_core.adapters.sqlite import SQLiteAdapter
from e_core.core.settings.db import DbSettings

if TYPE_CHECKING:
    from pathlib import Path


async def test_sqlite_crud_cycle(tmp_path: Path) -> None:
    adapter = SQLiteAdapter(DbSettings(db_path=tmp_path / "kv.db"))
    async with adapter:
        await adapter.set("user:1", b"one")
        assert await adapter.get("user:1") == b"one"
        assert await adapter.get("missing") is None

        await adapter.set("user:2", b"two")
        await adapter.set("other:1", b"x")
        assert [key async for key in adapter.keys("user:")] == ["user:1", "user:2"]

        await adapter.delete("user:1")
        assert await adapter.get("user:1") is None
        await adapter.delete("user:1")  # idempotent


async def test_sqlite_creates_absent_parents(tmp_path: Path) -> None:
    """connect() builds the whole parent chain — off the loop, before the file opens."""
    adapter = SQLiteAdapter(DbSettings(db_path=tmp_path / "deep" / "nested" / "kv.db"))
    async with adapter:
        await adapter.set("k", b"v")
        assert await adapter.get("k") == b"v"


async def test_sqlite_close_survives_double(tmp_path: Path) -> None:
    adapter = SQLiteAdapter(DbSettings(db_path=tmp_path / "kv.db"))
    await adapter.connect()
    await adapter.close()
    await adapter.close()  # closing a closed store is a no-op, not an error


async def test_sqlite_closed_adapter_refuses(tmp_path: Path) -> None:
    adapter = SQLiteAdapter(DbSettings(db_path=tmp_path / "kv.db"))
    async with adapter:
        pass
    with pytest.raises(RuntimeError, match="not connected"):
        await adapter.get("anything")
