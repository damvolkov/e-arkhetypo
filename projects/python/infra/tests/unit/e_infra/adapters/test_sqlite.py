"""tests/unit/e_infra/adapters/sqlite: the full KV lifecycle on one embedded file."""

from typing import TYPE_CHECKING

import pytest

from e_infra.adapters.base import PingError
from e_infra.adapters.sqlite import SQLiteAdapter
from e_infra.infra.config.db import DbSettings

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


async def test_sqlite_ping(tmp_path: Path) -> None:
    """One trivial statement on the open file; closed, nothing answers."""
    adapter = SQLiteAdapter(DbSettings(db_path=tmp_path / "kv.db"))
    async with adapter:
        await adapter.ping()
    with pytest.raises(PingError, match=r"^sqlite: RuntimeError: SQLiteAdapter not connected") as caught:
        await adapter.ping()
    assert (caught.value.adapter, caught.value.reason.partition(":")[0]) == ("sqlite", "RuntimeError")
