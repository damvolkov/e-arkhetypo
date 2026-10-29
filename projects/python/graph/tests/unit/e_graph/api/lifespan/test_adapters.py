"""tests/unit/e_graph/api/lifespan/adapters: every edge pinged at once at startup — one event each, never a failed
start."""

from datetime import timedelta
from typing import TYPE_CHECKING, Final

from litestar.testing import TestClient

from adapters.base import PingError
from adapters.sqlite import SQLiteAdapter
from e_graph.main import create_app

if TYPE_CHECKING:
    import pytest

LIMIT: Final[timedelta] = timedelta(seconds=1)
EDGES: Final[list[str]] = ["store", "telemetry", "redis", "http", "docling"]


async def test_adapters_ping_every_edge(client: TestClient) -> None:
    """In field order, `store` the only required edge; the open sqlite file, the in-process telemetry provider and the
    open client always answer."""
    pings = {ping.name: ping for ping in await client.app.state.system.infra.adapters.ping(LIMIT)}
    assert list(pings) == EDGES
    assert [pings[name].required for name in EDGES] == [True, False, False, False, False]
    assert (pings["store"].ok, pings["telemetry"].ok, pings["http"].ok) == (True, True, True)


async def test_adapters_startup_logs_each_ping(
    monkeypatch: pytest.MonkeyPatch, logs: list[tuple[str, str, dict[str, object]]]
) -> None:
    """One event per edge as the app starts: info when it answers, a warning when it does not — the app still starts."""

    async def down(_self: SQLiteAdapter) -> None:
        raise PingError(SQLiteAdapter.name, "disk gone")

    monkeypatch.setattr(SQLiteAdapter, "ping", down)
    with TestClient(create_app()) as client:
        assert client.get("/health").status_code == 200
    pings = {
        fields["adapter"]: {"log_level": level, **fields} for level, event, fields in logs if event == "adapter ping"
    }
    assert list(pings) == EDGES
    assert (pings["store"]["log_level"], pings["store"]["ok"], pings["store"]["reason"]) == (
        "warning",
        False,
        "sqlite: disk gone",
    )
    assert (pings["telemetry"]["log_level"], pings["telemetry"]["required"]) == ("info", False)
