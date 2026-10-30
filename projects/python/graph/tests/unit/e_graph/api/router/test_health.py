"""tests/unit/e_graph/api/router/health: liveness touches nothing; readiness surveys every provider and answers by the
required ones."""

from typing import TYPE_CHECKING

import pytest

from providers.drivers.documents.docling import DoclingDriver
from providers.drivers.store.sqlite import SqliteDriver

if TYPE_CHECKING:
    from litestar.testing import TestClient


async def test_health_touches_nothing(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


async def test_ready_answers_every_edge(client: TestClient) -> None:
    """Every provider's verdict in the body, in field order; the required store answers, so the service is ready."""
    response = client.get("/ready")
    body = response.json()
    assert (response.status_code, [each["name"] for each in body]) == (
        200,
        ["store", "telemetry", "redis", "http", "docling", "pages"],
    )
    assert all(each["latency"] >= 0 and set(each) == {"name", "required", "ok", "latency", "reason"} for each in body)


@pytest.mark.parametrize(
    ("provider", "role", "status"),
    [(DoclingDriver, "docling", 200), (SqliteDriver, "store", 503)],
    ids=["optional-down", "required-down"],
)
async def test_ready_required(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    provider: type[SqliteDriver | DoclingDriver],
    role: str,
    status: int,
) -> None:
    """Only a required provider down makes the service unready; an optional one is reported and nothing more."""

    async def down(_self: object) -> bool:
        return False

    monkeypatch.setattr(provider, "health", down)
    response = client.get("/ready")
    verdict = {each["name"]: each for each in response.json()}[role]
    assert (response.status_code, verdict["ok"], verdict["reason"]) == (status, False, "unhealthy")
