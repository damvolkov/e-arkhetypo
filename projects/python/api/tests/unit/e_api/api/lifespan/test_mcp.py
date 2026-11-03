"""tests/unit/e_api/api/lifespan/mcp: the server built over the door's tools — the transport accepts this service's Host
and Origin and no other's; the settings say which."""

from typing import TYPE_CHECKING

from litestar.testing import AsyncTestClient

from e_api.api.lifespan import mcp as lifespan
from e_api.main import create_app
from infra.settings import Settings
from support.mcp import BASE

if TYPE_CHECKING:
    import pytest

HEADERS = {"accept": "application/json, text/event-stream", "content-type": "application/json"}
INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}},
}


async def test_mcp_hosts_default_to_this_port() -> None:
    async with AsyncTestClient(create_app(), base_url=BASE) as client:
        answers = [
            (await client.post("/mcp", json=INIT, headers={**HEADERS, "host": host})).status_code
            for host in ("127.0.0.1:8000", "localhost:8000", "127.0.0.1:9999")
        ]
    assert answers == [200, 200, 421]


async def test_mcp_hosts_and_origins_follow_the_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    conf = Settings.load(mcp={"hosts": ["api.example.org"], "origins": ["https://api.example.org"]}, app={"port": 8000})
    monkeypatch.setattr(lifespan, "st", conf)
    async with AsyncTestClient(create_app(), base_url=BASE) as client:
        answers = [
            (await client.post("/mcp", json=INIT, headers={**HEADERS, "host": host, **origin})).status_code
            for host, origin in (
                ("api.example.org", {"origin": "https://api.example.org"}),
                ("api.example.org", {"origin": "https://evil.example"}),
                ("127.0.0.1:8000", {}),
            )
        ]
    assert answers == [200, 403, 421]
