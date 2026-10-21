"""tests/unit: the edge transports live — CORS preflight and correlation id propagation."""

from uuid import uuid4


def test_cors_preflight_is_answered(client) -> None:
    response = client.options(
        "/users",
        headers={"origin": "http://elsewhere.test", "access-control-request-method": "POST"},
    )
    assert response.status_code in (200, 204)
    assert response.headers["access-control-allow-origin"] == "*"
    assert "POST" in response.headers["access-control-allow-methods"]


def test_correlation_id_echoes_and_unique(client) -> None:
    first = client.get("/health").headers["x-request-id"]
    second = client.get("/health").headers["x-request-id"]
    assert first
    assert second
    assert first != second

    incoming = str(uuid4())
    assert client.get("/health", headers={"x-request-id": incoming}).headers["x-request-id"] == incoming
    ### garbage in is rejected by the middleware validator: a fresh id comes out instead
    assert client.get("/health", headers={"x-request-id": "not-a-uuid"}).headers["x-request-id"] != "not-a-uuid"
