"""tests/unit/e_infra/infra/config/providers/drivers/database/psqlpy: PsqlpySettings — the DSN is a secret, the pool a floor of one."""

from datetime import timedelta

import pytest
from pydantic import ValidationError

from e_infra.infra.config.providers.drivers.database.psqlpy import PsqlpySettings


def test_psqlpy_default_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    conf = PsqlpySettings()
    assert (conf.pool, conf.timeout) == (8, timedelta(seconds=30))
    monkeypatch.setenv("POSTGRES_DSN", "postgresql://u:hunter2@db:5432/x")
    monkeypatch.setenv("POSTGRES_POOL", "3")
    conf = PsqlpySettings()
    assert (conf.dsn.get_secret_value(), conf.pool) == ("postgresql://u:hunter2@db:5432/x", 3)
    assert "hunter2" not in repr(conf)


def test_psqlpy_pool_is_positive() -> None:
    with pytest.raises(ValidationError):
        PsqlpySettings(pool=0)
