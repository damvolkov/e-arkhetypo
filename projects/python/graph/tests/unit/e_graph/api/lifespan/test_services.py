"""tests/unit/e_graph/api/lifespan/services: the health engine built over every provider the providers lifespan opened,
surveyed at once at startup — one event each, never a failed start."""

from typing import TYPE_CHECKING, Final

from litestar.testing import TestClient

from e_graph.main import create_app
from providers.drivers.sqlite import SqliteDriver

if TYPE_CHECKING:
    import pytest

ROLES: Final[list[str]] = ["store", "telemetry", "redis", "http", "docling", "pages"]


async def test_services_health_surveys_every_provider(client: TestClient) -> None:
    """In field order, `store` the only required provider; the open sqlite file, the in-process telemetry provider, the
    open client and the loaded parser always answer."""
    verdicts = {each.name: each for each in await client.app.state.system.infra.engines.health.survey()}
    assert list(verdicts) == ROLES
    assert [verdicts[name].required for name in ROLES] == [True, False, False, False, False, False]
    assert {name: verdicts[name].ok for name in ("store", "telemetry", "http", "pages")} == dict.fromkeys(
        ("store", "telemetry", "http", "pages"), True
    )


async def test_services_startup_logs_each_verdict(
    monkeypatch: pytest.MonkeyPatch, logs: list[tuple[str, str, dict[str, object]]]
) -> None:
    """One event per provider as the app starts: info when it answers, a warning when it does not — the app still
    starts."""

    async def down(_self: SqliteDriver) -> bool:
        return False

    monkeypatch.setattr(SqliteDriver, "health", down)
    with TestClient(create_app()) as client:
        assert client.get("/health").status_code == 200
    verdicts = {
        fields["provider"]: {"log_level": level, **fields}
        for level, event, fields in logs
        if event == "provider health"
    }
    assert list(verdicts) == ROLES
    assert (verdicts["store"]["log_level"], verdicts["store"]["ok"], verdicts["store"]["reason"]) == (
        "warning",
        False,
        "unhealthy",
    )
    assert (verdicts["telemetry"]["log_level"], verdicts["telemetry"]["required"]) == ("info", False)
