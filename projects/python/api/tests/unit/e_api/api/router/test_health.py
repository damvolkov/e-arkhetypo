"""tests/unit/e_api/api/router/health: liveness touches nothing; readiness surveys every provider and answers by the
required ones."""

from dataclasses import fields
from typing import TYPE_CHECKING

import pytest

from e_api.api.lifespan.providers import ProvidersState
from providers.drivers.store.redis import RedisDriver
from providers.drivers.store.sqlite import SqliteDriver

if TYPE_CHECKING:
    from litestar.testing import TestClient


async def test_health_touches_nothing(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


async def test_ready_answers_every_provider(client: TestClient) -> None:
    """Every provider's verdict in the body, in field order; the required store answers, so the service is ready."""
    response = client.get("/ready")
    body = response.json()
    assert (response.status_code, [each["name"] for each in body]) == (
        200,
        [each.name for each in fields(ProvidersState)],
    )
    assert all(each["latency"] >= 0 and set(each) == {"name", "required", "ok", "latency", "reason"} for each in body)


@pytest.mark.parametrize(
    ("driver", "role", "status"),
    [(RedisDriver, "redis", 200), (SqliteDriver, "store", 503)],
    ids=["optional-down", "required-down"],
)
async def test_ready_required(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    driver: type[SqliteDriver | RedisDriver],
    role: str,
    status: int,
) -> None:
    """Only a required provider down makes the service unready; an optional one is reported and nothing more."""

    async def down(_self: object) -> bool:
        return False

    monkeypatch.setattr(driver, "health", down)
    response = client.get("/ready")
    verdicts = {each["name"]: each for each in response.json()}
    assert (response.status_code, verdicts[role]["ok"], verdicts[role]["reason"]) == (status, False, "unhealthy")
