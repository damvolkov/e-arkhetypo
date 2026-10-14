import logging

import httpx2
import pytest
from fakes import lifespan

from core.settings.base import Secret
from e_mcp.config.mcp import McpSettings
from e_mcp.main import _ToStructlog, assemble
from e_mcp.mcp.guard import TokenGuard

INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}},
}
HEADERS = {
    "accept": "application/json, text/event-stream",
    "content-type": "application/json",
    "host": "127.0.0.1:45200",
}


@pytest.mark.parametrize(("token", "guarded"), [(Secret("t"), True), (None, False)], ids=["token", "open"])
async def test_main_assemble(token: Secret | None, guarded: bool) -> None:
    app = assemble(McpSettings(token=token))
    assert isinstance(app, TokenGuard) is guarded


async def test_main_assemble_default(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("MCP_HOST", "MCP_PORT", "MCP_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    assert not isinstance(assemble(), TokenGuard)


async def test_main_quiet_routes_stdlib() -> None:
    _ = assemble(McpSettings())
    assert any(isinstance(h, _ToStructlog) for h in logging.root.handlers)
    assert not any(type(h).__module__.startswith("rich") for h in logging.root.handlers)
    logging.getLogger("mcp.test").warning("routed without raising")


@pytest.mark.parametrize(
    ("headers", "status"),
    [
        ({**HEADERS, "authorization": "Bearer t"}, 200),
        (HEADERS, 401),
        ({**HEADERS, "authorization": "Bearer wrong"}, 401),
        ({**HEADERS, "authorization": "Bearer t", "host": "evil.example:45200"}, 421),
    ],
    ids=["authorized", "no-token", "wrong-token", "foreign-host"],
)
async def test_main_http_initialize(settings: McpSettings, headers: dict, status: int) -> None:
    app = assemble(settings)
    async with (
        lifespan(app),
        httpx2.AsyncClient(transport=httpx2.ASGITransport(app), base_url="http://127.0.0.1:45200") as http,
    ):
        response = await http.post("/mcp", json=INIT, headers=headers)
    assert response.status_code == status


async def test_main_http_tool_call(settings: McpSettings) -> None:
    app = assemble(settings)
    auth = {**HEADERS, "authorization": "Bearer t"}
    async with (
        lifespan(app),
        httpx2.AsyncClient(transport=httpx2.ASGITransport(app), base_url="http://127.0.0.1:45200") as http,
    ):
        init = await http.post("/mcp", json=INIT, headers=auth)
        session = {**auth, "mcp-session-id": init.headers["mcp-session-id"], "mcp-protocol-version": "2025-06-18"}
        await http.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=session)
        call = await http.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "greet", "arguments": {"name": "metaxy"}},
            },
            headers=session,
        )
    answer = call.json()["result"]["structuredContent"]
    assert answer == {"message": "hello metaxy", "port": 45200}
