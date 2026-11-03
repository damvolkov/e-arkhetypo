"""tests/unit/e_infra/infra/config/providers/drivers/cache/postgres: CachePostgresSettings — how long a durable value lives."""

from datetime import timedelta
from typing import TYPE_CHECKING

from e_infra.infra.config.providers.drivers.cache.postgres import CachePostgresSettings

if TYPE_CHECKING:
    import pytest


def test_cache_postgres_default_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    assert CachePostgresSettings().ttl == timedelta(days=1)
    monkeypatch.setenv("CACHE_TTL", "PT5M")
    assert CachePostgresSettings().ttl == timedelta(minutes=5)
    assert CachePostgresSettings(ttl=None).ttl is None
