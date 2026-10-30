"""tests/unit/e_infra/infra/config/cache: CacheSettings — entries in memory and how long a value lives."""

from datetime import timedelta

import pytest
from pydantic import ValidationError

from e_infra.infra.config.cache import CacheSettings


def test_cache_default_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    assert (CacheSettings().size, CacheSettings().ttl) == (50_000, timedelta(days=1))
    monkeypatch.setenv("CACHE_SIZE", "10")
    monkeypatch.setenv("CACHE_TTL", "PT5M")
    assert (CacheSettings().size, CacheSettings().ttl) == (10, timedelta(minutes=5))


def test_cache_size_is_positive() -> None:
    with pytest.raises(ValidationError):
        CacheSettings(size=0)
