"""tests/unit/e_api/api/middlewares: the CORS translation resolves settings at call time, never at import; the edge
transports live — preflight answered, correlation id propagated; the access log, per request."""

from uuid import uuid4

from e_api.api.middlewares import cors_config
from infra.config.api import APISettings, HTTPMethod


def test_cors_config_reads_the_singleton_when_no_settings_given() -> None:
    config = cors_config()
    assert config.allow_origins == ["*"]


def test_cors_config_honours_explicit_settings() -> None:
    config = cors_config(APISettings(allow_origins=["https://eager.test"], allow_methods=[HTTPMethod.GET]))
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


def test_cors_preflight_is_answered(client) -> None:
    response = client.options(
        "/users",
        headers={"origin": "http://elsewhere.test", "access-control-request-method": "POST"},
    )
    assert response.status_code in (200, 204)
    assert response.headers["access-control-allow-origin"] == "*"
    assert "POST" in response.headers["access-control-allow-methods"]


def test_correlation_id_is_unique_per_request(client) -> None:
    first = client.get("/health").headers["x-request-id"]
    second = client.get("/health").headers["x-request-id"]
    assert (bool(first), bool(second), first != second) == (True, True, True)


def test_correlation_id_echoes_a_valid_incoming_one(client) -> None:
    incoming = str(uuid4())
    assert client.get("/health", headers={"x-request-id": incoming}).headers["x-request-id"] == incoming


def test_correlation_id_replaces_garbage(client) -> None:
    """Garbage in is rejected by the middleware validator: a fresh id comes out instead."""
    assert client.get("/health", headers={"x-request-id": "not-a-uuid"}).headers["x-request-id"] != "not-a-uuid"
