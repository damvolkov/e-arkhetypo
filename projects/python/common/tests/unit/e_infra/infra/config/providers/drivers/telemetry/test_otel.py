"""tests/unit/e_infra/infra/config/providers/drivers/telemetry/otel: OtelSettings — collector, secret headers, bounds and sampling."""

from datetime import timedelta

import pytest
from pydantic import ValidationError

from e_infra.infra.config.providers.drivers.telemetry.otel import OtelProtocol, OtelSettings


def test_otel_default_exports_nowhere() -> None:
    conf = OtelSettings()
    assert (conf.endpoint, conf.protocol, conf.sample, conf.timeout) == (
        "",
        OtelProtocol.HTTP,
        1.0,
        timedelta(seconds=10),
    )


def test_otel_env_headers_are_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTEL_ENDPOINT", "https://collector.test")
    monkeypatch.setenv("OTEL_HEADERS", '{"authorization": "hunter2"}')
    conf = OtelSettings()
    assert conf.headers["authorization"].get_secret_value() == "hunter2"
    assert "hunter2" not in repr(conf)


@pytest.mark.parametrize("sample", [-0.1, 1.1])
def test_otel_sample_is_a_share(sample: float) -> None:
    with pytest.raises(ValidationError):
        OtelSettings(sample=sample)
