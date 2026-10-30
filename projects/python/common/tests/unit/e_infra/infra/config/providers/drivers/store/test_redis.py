"""tests/unit/e_infra/infra/config/providers/drivers/store/redis: RedisSettings — a secret URL, a pool and a socket timeout."""

from datetime import timedelta

import pytest
from pydantic import ValidationError

from e_infra.infra.config.providers.drivers.store.redis import RedisSettings


def test_redis_default_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    conf = RedisSettings()
    assert (conf.url.get_secret_value(), conf.pool, conf.timeout) == (
        "redis://localhost:6379/0",
        10,
        timedelta(seconds=5),
    )
    monkeypatch.setenv("REDIS_URL", "redis://:hunter2@cache:6379/1")
    conf = RedisSettings()
    assert conf.url.get_secret_value() == "redis://:hunter2@cache:6379/1"
    assert "hunter2" not in repr(conf)


def test_redis_pool_is_positive() -> None:
    with pytest.raises(ValidationError):
        RedisSettings(pool=0)
