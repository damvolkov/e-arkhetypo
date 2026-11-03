"""tests/unit/e_api/mcp/state: the OST parity of the door — `system.mcp` is the section of `e_api/mcp/state.py`, its server
the engine's over the door's registry, built by the lifespan that runs it."""

from typing import TYPE_CHECKING

from litestar.testing import AsyncTestClient

from e_api.api.lifespan import mcp as lifespan
from e_api.main import create_app
from e_api.mcp.instructions import INSTRUCTIONS
from e_api.mcp.registry import ROUTES
from e_api.mcp.state import McpState
from infra.mcp.server import McpServer
from infra.settings import Settings
from support.mcp import BASE

if TYPE_CHECKING:
    import pytest
    from litestar import Litestar

HEADERS = {"accept": "application/json, text/event-stream", "content-type": "application/json"}
INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}},
}


async def test_state_section_holds_the_server(client: AsyncTestClient[Litestar]) -> None:
    """The branch `mcp` is the package `e_api.mcp`: its section is that package's `state`, its server the engine's."""
    section = client.app.state.system.mcp
    assert (type(section).__module__, type(section), type(section.server), len(section.server.registry)) == (
        "e_api.mcp.state",
        McpState,
        McpServer,
        len(ROUTES),
    )
    assert section.server.instructions == INSTRUCTIONS


async def test_state_hosts_default_to_this_port(client: AsyncTestClient[Litestar]) -> None:
    answers = [
        (await client.post("/mcp", json=INIT, headers={**HEADERS, "host": host})).status_code
        for host in ("127.0.0.1:8000", "localhost:8000", "127.0.0.1:9999")
    ]
    assert answers == [200, 200, 421]


async def test_state_hosts_and_origins_follow_the_settings(monkeypatch: pytest.MonkeyPatch) -> None:
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
