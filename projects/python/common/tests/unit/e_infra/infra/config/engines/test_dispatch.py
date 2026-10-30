"""tests/unit/e_infra/infra/config/engines/dispatch: DispatchSettings — which durable queue backs the background."""

from datetime import timedelta

import pytest
from pydantic import ValidationError

from e_infra.infra.config.engines.dispatch import DispatchSettings, QueueEngine


def test_dispatch_default_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    assert (DispatchSettings().engine, DispatchSettings().throttle) == (QueueEngine.PGQUEUER, timedelta(seconds=0.5))
    monkeypatch.setenv("QUEUE_ENGINE", "awa")
    assert DispatchSettings().engine is QueueEngine.AWA


def test_dispatch_engine_rejects_a_typo() -> None:
    with pytest.raises(ValidationError):
        DispatchSettings(engine="rabbit")
