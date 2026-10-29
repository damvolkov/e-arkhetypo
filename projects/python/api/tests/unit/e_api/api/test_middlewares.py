"""tests/unit: api.middlewares — the CORS translation resolves settings at call time, never at import."""

from e_api.api.middlewares import cors_config
from infra.config.api import ApiSettings, HttpMethod


def test_cors_config_reads_the_singleton_when_no_settings_given() -> None:
    config = cors_config()
    assert config.allow_origins == ["*"]


def test_cors_config_honours_explicit_settings() -> None:
    config = cors_config(ApiSettings(allow_origins=["https://eager.test"], allow_methods=[HttpMethod.GET]))
    assert config.allow_origins == ["https://eager.test"]
    assert config.allow_methods == ["GET"]
