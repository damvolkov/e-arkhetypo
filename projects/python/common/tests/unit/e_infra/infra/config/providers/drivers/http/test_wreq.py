"""tests/unit/e_infra/infra/config/providers/drivers/http/wreq: WreqSettings — a base URL and a request bound."""

from datetime import timedelta
from typing import TYPE_CHECKING

from e_infra.infra.config.providers.drivers.http.wreq import WreqSettings

if TYPE_CHECKING:
    import pytest


def test_wreq_default_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    assert WreqSettings().timeout == timedelta(seconds=10)
    monkeypatch.setenv("HTTP_BASE_URL", "https://api.test")
    monkeypatch.setenv("HTTP_TIMEOUT", "PT12.5S")
    conf = WreqSettings()
    assert (conf.base_url, conf.timeout) == ("https://api.test", timedelta(seconds=12.5))
