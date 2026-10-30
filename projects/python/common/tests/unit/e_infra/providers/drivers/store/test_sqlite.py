"""e_infra/providers/drivers/store/sqlite: the full KV lifecycle on one embedded file."""

from datetime import timedelta
from typing import TYPE_CHECKING, Any

import aiosqlite
import pytest

from e_infra.infra.config.providers.drivers.store.sqlite import SqliteSettings
from e_infra.infra.errors import StoreError
from e_infra.ports.store import StorePort
from e_infra.providers.drivers.store.sqlite import SqliteDriver
from support.kv import KV_CALLS

if TYPE_CHECKING:
    from pathlib import Path

    from unit.e_infra.conftest import Logs


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


async def test_sqlite_lifecycle_logs_and_the_busy_timeout_rides_the_connection(
    tmp_path: Path, logs: Logs, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[float] = []
    connect = aiosqlite.connect

    def spy(path: Path, **kwargs: Any) -> aiosqlite.Connection:
        seen.append(kwargs["timeout"])
        return connect(path, **kwargs)

    monkeypatch.setattr(aiosqlite, "connect", spy)
    async with SqliteDriver(SqliteSettings(path=tmp_path / "kv.db", timeout=timedelta(seconds=3))):
        pass
    assert (seen, logs.at("info")) == ([3.0], ["sqlite opened", "sqlite closed"])


async def test_sqlite_default_settings_come_from_the_composer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    async with SqliteDriver() as adapter:
        await adapter.set("k", b"v")
    assert (tmp_path / "data" / "app.db").exists()


async def test_sqlite_set_overwrites(tmp_path: Path) -> None:
    async with SqliteDriver(SqliteSettings(path=tmp_path / "kv.db")) as adapter:
        await adapter.set("k", b"one")
        await adapter.set("k", b"two")
        assert await adapter.get("k") == b"two"


@pytest.mark.parametrize("call", KV_CALLS)
async def test_sqlite_error_translated_and_logged(tmp_path: Path, logs: Logs, call: str) -> None:
    """aiosqlite's own error never leaves the driver."""
    async with SqliteDriver(SqliteSettings(path=tmp_path / "kv.db")) as adapter:
        await adapter._common_open().execute("DROP TABLE kv")
        with pytest.raises(StoreError):
            await KV_CALLS[call](adapter)
    assert logs.at("error") == ["sqlite failed"]


async def test_sqlite_health_false_and_warned_when_the_file_cannot_answer(
    tmp_path: Path, logs: Logs, monkeypatch: pytest.MonkeyPatch
) -> None:
    def locked(*_args: object, **_kwargs: object) -> None:
        msg = "database is locked"
        raise aiosqlite.OperationalError(msg)

    async with SqliteDriver(SqliteSettings(path=tmp_path / "kv.db")) as adapter:
        assert await adapter.health()
        monkeypatch.setattr(aiosqlite.Connection, "execute", locked)
        assert not await adapter.health()
    assert "sqlite unhealthy" in logs.at("warning")


async def test_sqlite_open_on_a_path_that_is_a_directory_is_a_store_error(tmp_path: Path, logs: Logs) -> None:
    with pytest.raises(StoreError):
        await SqliteDriver(SqliteSettings(path=tmp_path)).__aenter__()
    assert logs.at("error") == ["sqlite failed"]
