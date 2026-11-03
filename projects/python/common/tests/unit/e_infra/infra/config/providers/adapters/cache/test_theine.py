"""tests/unit/e_infra/infra/config/providers/adapters/cache/theine: TheineSettings — entries in memory and how long a value lives."""

from datetime import timedelta

import pytest
from pydantic import ValidationError

from e_infra.infra.config.providers.adapters.cache.theine import TheineSettings


def test_cache_default_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    assert (TheineSettings().size, TheineSettings().ttl) == (50_000, timedelta(days=1))
    monkeypatch.setenv("CACHE_SIZE", "10")
    monkeypatch.setenv("CACHE_TTL", "PT5M")
    assert (TheineSettings().size, TheineSettings().ttl) == (10, timedelta(minutes=5))


def test_cache_size_is_positive() -> None:
    with pytest.raises(ValidationError):
        TheineSettings(size=0)
