"""tests/unit/e_infra/infra/config/providers/drivers/queue/awa: AwaSettings — the queue's own database and a pool awa can run on."""

from datetime import timedelta

import pytest
from pydantic import ValidationError

from e_infra.infra.config.providers.drivers.queue.awa import AwaSettings


def test_awa_default_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    conf = AwaSettings()
    assert (conf.pool, conf.timeout, conf.drain) == (10, timedelta(seconds=5), timedelta(seconds=5))
    assert conf.dsn.get_secret_value().endswith("/app_background")
    monkeypatch.setenv("QUEUE_DSN", "postgresql://u:hunter2@db/q")
    assert "hunter2" not in repr(AwaSettings())


def test_awa_pool_has_a_floor() -> None:
    with pytest.raises(ValidationError):
        AwaSettings(pool=5)
