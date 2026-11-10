"""tests/unit/e_api/mcp/mount: /mcp over HTTP through the mount — initialize, call a tool, refuse a foreign host; the
caller the token middleware resolved reaching the tool, a bad key refused as the API refuses it, a tool's own route kept
to the engine."""

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Final

import pytest
from litestar.status_codes import HTTP_401_UNAUTHORIZED
from litestar.testing import AsyncTestClient
from mcp import types

from e_api import main
from e_api.infra.settings import Settings
from e_api.main import create_app
from e_api.mcp import mount
from support.mcp import BASE

if TYPE_CHECKING:
    from litestar import Litestar

    from support.auth import FakeAuth

HEADERS: Final = {"accept": "application/json, text/event-stream", "content-type": "application/json"}
INIT: Final = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}},
}


def rpc(ident: int, method: str, params: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": ident, "method": method, "params": params}


async def opened(client: AsyncTestClient[Litestar], key: dict[str, str]) -> dict[str, str]:
    """An initialized session's headers, the key sent on every request as a harness's MCP config sends it."""
    started = await client.post("/mcp", json=INIT, headers={**HEADERS, **key})
    session = {
        **HEADERS,
        **key,
        "mcp-session-id": started.headers["mcp-session-id"],
        "mcp-protocol-version": "2025-06-18",
    }
    await client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=session)
    return session


async def test_mount_initialize_then_call(client: AsyncTestClient[Litestar]) -> None:
    opened_ = await client.post("/mcp", json=INIT, headers=HEADERS)
    session = {**HEADERS, "mcp-session-id": opened_.headers["mcp-session-id"], "mcp-protocol-version": "2025-06-18"}
    await client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=session)
    called = await client.post(
        "/mcp", json=rpc(2, "tools/call", {"name": "api_health", "arguments": {}}), headers=session
    )
    assert (opened_.json()["result"]["serverInfo"]["name"], called.json()["result"]["structuredContent"]) == (
        "e-api",
        {"status": "ok"},
    )


async def test_mount_refuses_a_foreign_host(client: AsyncTestClient[Litestar]) -> None:
    refused = await client.post("/mcp", json=INIT, headers={**HEADERS, "host": "evil.example:8000"})
    assert refused.status_code == 421


async def test_mount_tool_reads_the_middlewares_caller(
    client: AsyncTestClient[Litestar], ana_key: dict[str, str]
) -> None:
    session = await opened(client, ana_key)
    called = await client.post(
        "/mcp", json=rpc(2, "tools/call", {"name": "api_user_list", "arguments": {}}), headers=session
    )
    assert called.json()["result"].get("isError", False) is False


async def test_mount_nobody_refused_in_the_apis_words(client: AsyncTestClient[Litestar]) -> None:
    session = await opened(client, {})
    called = await client.post(
        "/mcp", json=rpc(2, "tools/call", {"name": "api_user_list", "arguments": {}}), headers=session
    )
    result = called.json()["result"]
    ### the refusal is the API's own message, word for word.
    assert (result["isError"], result["content"][0]["text"]) == (
        True,
        "user access: send a key (Authorization: Bearer)",
    )


async def test_mount_unknown_key_refused_as_the_api_refuses_it(client: AsyncTestClient[Litestar]) -> None:
    refused = await client.post("/mcp", json=INIT, headers={**HEADERS, "Authorization": "Bearer stolen"})
    assert (refused.status_code, refused.json()["detail"], refused.headers["www-authenticate"]) == (
        HTTP_401_UNAUTHORIZED,
        "unknown token: it names no account",
        'Bearer error="invalid_token"',
    )


async def test_mount_revoked_key_is_a_401(client: AsyncTestClient[Litestar], keys: FakeAuth) -> None:
    await keys.revoke("ana")
    refused = await client.post("/mcp", json=INIT, headers={**HEADERS, "Authorization": "Bearer t-ana"})
    assert (refused.status_code, refused.json()["detail"]) == (
        HTTP_401_UNAUTHORIZED,
        "revoked token: ask for a new one",
    )


@pytest.mark.parametrize("key", [{}, {"Authorization": "Bearer t-ana"}], ids=["nobody", "a-key"])
async def test_mount_a_tool_route_answers_the_engine_only(
    client: AsyncTestClient[Litestar], key: dict[str, str]
) -> None:
    """A tool's route reached straight over HTTP, with or without a key, is refused: only the MCP engine calls it."""
    answered = await client.post("/mcp/tools/api_user_list", json={}, headers=key)
    assert (answered.status_code, answered.json()["detail"]) == (
        403,
        "an MCP tool: called through the MCP endpoint only",
    )


async def test_mount_unknown_tool(client: AsyncTestClient[Litestar]) -> None:
    session = await opened(client, {})
    called = await client.post(
        "/mcp", json=rpc(2, "tools/call", {"name": "api_ghost", "arguments": {}}), headers=session
    )
    result = called.json()["result"]
    assert (result["isError"], result["content"][0]["text"]) == (True, "no tool 'api_ghost': tools/list names them")


async def test_mount_a_call_off_http_is_refused(client: AsyncTestClient[Litestar]) -> None:
    """A call with no HTTP request behind it (an in-process transport) has no caller to carry: refused, never anonymous."""
    server = client.app.state.system.mcp.server
    result = await server._call_tool(
        SimpleNamespace(request=None), types.CallToolRequestParams(name="api_health", arguments={})
    )
    assert (result.is_error, result.content[0].text) == (True, "a tool is called over HTTP, through the MCP endpoint")


async def test_mount_follows_the_path_the_settings_say(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "st", Settings(MCP_PATH="/agents"))
    async with AsyncTestClient(create_app(), base_url=BASE) as client:
        moved, old = (
            await client.post("/agents", json=INIT, headers=HEADERS),
            await client.post("/mcp", json=INIT, headers=HEADERS),
        )
    assert (moved.status_code, old.status_code) == (200, 404)


def test_mount_routes_answer_on_the_path_given() -> None:
    assert [route.paths for route in mount.routes(path="/x")] == [{"/x"}]
