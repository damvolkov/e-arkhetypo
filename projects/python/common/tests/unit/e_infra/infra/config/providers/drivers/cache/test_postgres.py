"""tests/unit/e_infra/infra/config/providers/drivers/cache/postgres: PostgresCacheSettings — how long a durable value lives."""

from datetime import timedelta
from typing import TYPE_CHECKING

from e_infra.infra.config.providers.drivers.cache.postgres import PostgresCacheSettings

if TYPE_CHECKING:
    import pytest


def test_cache_postgres_default_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    assert PostgresCacheSettings().ttl == timedelta(days=1)
    monkeypatch.setenv("CACHE_TTL", "PT5M")
    assert PostgresCacheSettings().ttl == timedelta(minutes=5)
    assert PostgresCacheSettings(ttl=None).ttl is None
