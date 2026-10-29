"""tests/unit/e_infra/adapters/ports: structural conformance — every adapter satisfies its port by shape."""

from typing import TYPE_CHECKING

from e_infra.adapters.http import HttpAdapter
from e_infra.adapters.ports import HttpPort, StorePort
from e_infra.adapters.redis import RedisAdapter
from e_infra.adapters.sqlite import SQLiteAdapter
from e_infra.infra.config.db import DbSettings
from e_infra.infra.config.http import HttpSettings
from e_infra.infra.config.redis import RedisSettings

if TYPE_CHECKING:
    from pathlib import Path


async def test_ports_sqlite_satisfies_store(tmp_path: Path) -> None:
    assert isinstance(SQLiteAdapter(DbSettings(db_path=tmp_path / "kv.db")), StorePort)


async def test_ports_redis_satisfies_store() -> None:
    assert isinstance(RedisAdapter(RedisSettings()), StorePort)


async def test_ports_http_satisfies_client() -> None:
    assert isinstance(HttpAdapter(HttpSettings()), HttpPort)
