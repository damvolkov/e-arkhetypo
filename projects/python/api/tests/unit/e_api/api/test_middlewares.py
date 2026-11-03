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


def test_access_log_records_a_request_at_its_status(client, request_logs) -> None:
    client.get("/health")
    assert [(each["path"], each["status"]) for each in request_logs.requests] == [("/health", 200)]


def test_access_log_records_a_refused_key_at_its_status(client, request_logs) -> None:
    """The key is refused by a middleware below the log: litestar answers it above, and the line says 401."""
    answered = client.get("/users", headers={"Authorization": "Bearer stolen"})
    assert (answered.status_code, [(each["path"], each["status"]) for each in request_logs.requests]) == (
        401,
        [("/users", 401)],
    )
