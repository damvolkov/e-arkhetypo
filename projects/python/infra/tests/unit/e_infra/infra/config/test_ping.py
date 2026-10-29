"""tests/unit/e_infra/infra/config: PingSettings — how long one adapter's ping may take, default and env."""

from datetime import timedelta
from typing import TYPE_CHECKING

from e_infra.infra.config.ping import PingSettings

if TYPE_CHECKING:
    import pytest


def test_ping_default() -> None:
    assert PingSettings().timeout == timedelta(seconds=2)


def test_ping_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PING_TIMEOUT", "PT0.5S")
    assert PingSettings().timeout == timedelta(milliseconds=500)
