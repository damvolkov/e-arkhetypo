"""e_infra/providers/drivers/store/sqlite: the full KV lifecycle on one embedded file."""

from typing import TYPE_CHECKING

import pytest

from e_infra.infra.config.providers.drivers.store.sqlite import SqliteSettings
from e_infra.infra.errors import StoreError
from e_infra.ports.store import StorePort
from e_infra.providers.drivers.store.sqlite import SqliteDriver

if TYPE_CHECKING:
    from pathlib import Path


async def test_sqlite_crud_cycle(tmp_path: Path) -> None:
    adapter = SqliteDriver(SqliteSettings(path=tmp_path / "kv.db"))
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
    adapter = SqliteDriver(SqliteSettings(path=tmp_path / "deep" / "nested" / "kv.db"))
    async with adapter:
        await adapter.set("k", b"v")
        assert await adapter.get("k") == b"v"


async def test_sqlite_close_survives_double(tmp_path: Path) -> None:
    adapter = SqliteDriver(SqliteSettings(path=tmp_path / "kv.db"))
    await adapter.__aenter__()
    await adapter.__aexit__(None, None, None)
    await adapter.__aexit__(None, None, None)  # closing a closed store is a no-op, not an error


async def test_sqlite_closed_adapter_refuses(tmp_path: Path) -> None:
    adapter = SqliteDriver(SqliteSettings(path=tmp_path / "kv.db"))
    async with adapter:
        pass
    with pytest.raises(StoreError, match="not open"):
        await adapter.get("anything")


async def test_sqlite_health(tmp_path: Path) -> None:
    """One trivial statement on the open file; closed, nothing answers."""
    adapter = SqliteDriver(SqliteSettings(path=tmp_path / "kv.db"))
    async with adapter:
        assert isinstance(adapter, StorePort)
        assert await adapter.health()
    assert not await adapter.health()


async def test_sqlite_error_translated(tmp_path: Path) -> None:
    """aiosqlite's own error never leaves the driver."""
    async with SqliteDriver(SqliteSettings(path=tmp_path / "kv.db")) as adapter:
        await adapter._common_open().execute("DROP TABLE kv")
        with pytest.raises(StoreError):
            await adapter.get("k")
