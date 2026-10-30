"""tests/unit/e_infra/infra/config/providers/drivers/queue/pgqueuer: PgqueuerSettings — pace only; the database is the driver it rides."""

from datetime import timedelta

import pytest
from pydantic import ValidationError

from e_infra.infra.config.providers.drivers.queue.pgqueuer import PgqueuerSettings


def test_pgqueuer_default_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    conf = PgqueuerSettings()
    assert (conf.heartbeat, conf.restart, conf.poll) == (
        timedelta(seconds=30),
        timedelta(seconds=1),
        timedelta(milliseconds=200),
    )
    monkeypatch.setenv("QUEUE_RESTART", "PT0.5S")
    assert PgqueuerSettings().restart == timedelta(milliseconds=500)
    assert not {"dsn", "pool"} & set(PgqueuerSettings.model_fields)


def test_pgqueuer_heartbeat_is_positive() -> None:
    with pytest.raises(ValidationError):
        PgqueuerSettings(heartbeat=timedelta(0))
