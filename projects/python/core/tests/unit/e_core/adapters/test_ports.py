"""tests/unit/e_core/adapters/ports: structural conformance — every adapter satisfies its port by shape."""

from typing import TYPE_CHECKING

from e_core.adapters.http import HttpAdapter
from e_core.adapters.ports import HttpPort, StorePort
from e_core.adapters.redis import RedisAdapter
from e_core.adapters.sqlite import SQLiteAdapter
from e_core.core.settings.db import DbSettings
from e_core.core.settings.http import HttpSettings
from e_core.core.settings.redis import RedisSettings

if TYPE_CHECKING:
    from pathlib import Path


async def test_ports_sqlite_satisfies_store(tmp_path: Path) -> None:
    assert isinstance(SQLiteAdapter(DbSettings(db_path=tmp_path / "kv.db")), StorePort)


async def test_ports_redis_satisfies_store() -> None:
    assert isinstance(RedisAdapter(RedisSettings()), StorePort)


async def test_ports_http_satisfies_client() -> None:
    assert isinstance(HttpAdapter(HttpSettings()), HttpPort)
