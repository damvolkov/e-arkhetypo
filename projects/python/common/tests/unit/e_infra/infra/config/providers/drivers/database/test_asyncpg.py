"""tests/unit/e_infra/infra/config/providers/drivers/database/asyncpg: AsyncpgSettings — a secret DSN and a pool that bounds hold."""

from datetime import timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from e_infra.infra.config.providers.drivers.database.asyncpg import AsyncpgSettings


def test_asyncpg_default_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    conf = AsyncpgSettings()
    assert (conf.pool_min, conf.pool, conf.timeout) == (1, 8, timedelta(seconds=30))
    monkeypatch.setenv("ASYNCPG_DSN", "postgresql://u:hunter2@db:5432/x")
    monkeypatch.setenv("ASYNCPG_POOL", "4")
    conf = AsyncpgSettings()
    assert (conf.dsn.get_secret_value(), conf.pool) == ("postgresql://u:hunter2@db:5432/x", 4)
    assert "hunter2" not in repr(conf)


@pytest.mark.parametrize("fields", [{"pool": 0}, {"pool_min": -1}, {"pool_min": 9, "pool": 8}])
def test_asyncpg_rejects_at_load(fields: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        AsyncpgSettings(**fields)
