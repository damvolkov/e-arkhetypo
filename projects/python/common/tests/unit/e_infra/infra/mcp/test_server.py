"""tests/unit/e_infra/infra/mcp/server: /mcp over HTTP through the SDK's own client, both handshakes — the tools listed
as the registry holds them, a call answered by its route in process, a refusal the API's own words, a foreign host
refused, a tool route kept to the engine."""

from typing import TYPE_CHECKING, Any, Final

import pytest
from litestar.status_codes import HTTP_401_UNAUTHORIZED
from mcp import types

from support.mcp import MODES, call, refused

if TYPE_CHECKING:
    from litestar import Litestar
    from litestar.testing import AsyncTestClient

    from support.mcp import Connect
    from unit.e_infra.infra.mcp.conftest import Detached

HEADERS: Final = {"accept": "application/json, text/event-stream", "content-type": "application/json"}
INIT: Final = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}},
}


@pytest.mark.parametrize("mode", MODES)
async def test_server_lists_the_registry(connect: Connect, mode: str) -> None:
    async with connect(None, mode) as mcp:
        listed = (await mcp.list_tools()).tools
        instructions = mcp.instructions
    wipe = next(tool for tool in listed if tool.name == "probe_wipe")
    echo = next(tool for tool in listed if tool.name == "probe_echo")
    assert wipe.annotations is not None
    assert (
        sorted(tool.name for tool in listed),
        instructions,
        (wipe.annotations.read_only_hint, wipe.annotations.destructive_hint),
        echo.input_schema["required"],
        echo.input_schema["properties"]["times"],
        echo.output_schema is not None,
    ) == (
        ["probe_echo", "probe_refuse", "probe_whoami", "probe_wipe"],
        "A probe.",
        (False, True),
        ["text"],
        {"type": "integer", "default": 1},
        True,
    )


@pytest.mark.parametrize("mode", MODES)
async def test_server_call_is_answered_by_its_route(connect: Connect, mode: str) -> None:
    assert await call(connect, "probe_echo", {"text": "ab", "times": 2}, mode=mode) == {"text": "abab"}


async def test_server_defaults_apply(connect: Connect) -> None:
    assert await call(connect, "probe_echo", {"text": "ab"}) == {"text": "ab"}


async def test_server_a_list_is_wrapped_as_a_result(connect: Connect, root: dict[str, str]) -> None:
    assert await call(connect, "probe_wipe", {}, root) == {"result": ["everything"]}


@pytest.mark.parametrize("mode", MODES)
async def test_server_tool_reads_the_middlewares_caller(connect: Connect, ana: dict[str, str], mode: str) -> None:
    assert await call(connect, "probe_whoami", {}, ana, mode) == {"name": "ana", "role": "user"}


@pytest.mark.parametrize("mode", MODES)
async def test_server_nobody_refused_in_the_apis_words(connect: Connect, mode: str) -> None:
    assert await refused(connect, "probe_whoami", {}, mode=mode) == "user access: send a key (Authorization: Bearer)"


async def test_server_a_short_role_refused_in_the_apis_words(connect: Connect, ana: dict[str, str]) -> None:
    assert await refused(connect, "probe_wipe", {}, ana) == "admin access: this key's account is user"


async def test_server_the_routes_own_refusal(connect: Connect) -> None:
    assert await refused(connect, "probe_refuse", {}) == "nothing here"


async def test_server_validation_names_the_arguments(connect: Connect) -> None:
    assert (await refused(connect, "probe_echo", {"times": 2})).startswith("invalid arguments:")


async def test_server_unknown_tool(connect: Connect) -> None:
    assert await refused(connect, "probe_ghost", {}) == "no tool 'probe_ghost': tools/list names them"


async def test_server_a_call_off_http_is_refused(client: AsyncTestClient[Litestar], detached: Detached) -> None:
    """A call with no HTTP request behind it (an in-process transport) has no caller to carry: refused, never anonymous."""
    server = client.app.state["mcp"]
    result = await server._call_tool(detached, types.CallToolRequestParams(name="probe_echo", arguments={}))
    assert (result.is_error, result.content[0].text) == (True, "a tool is called over HTTP, through the MCP endpoint")


async def test_server_exposes_its_registry_and_instructions(client: AsyncTestClient[Litestar]) -> None:
    server = client.app.state["mcp"]
    assert (len(server.registry), server.instructions) == (4, "A probe.")


async def test_server_refuses_a_foreign_host(client: AsyncTestClient[Litestar]) -> None:
    answered = await client.post("/mcp", json=INIT, headers={**HEADERS, "host": "evil.example:8000"})
    assert answered.status_code == 421


@pytest.mark.parametrize("key", ["stolen", "t-gone"], ids=["unknown", "revoked"])
async def test_server_a_bad_key_is_a_401_before_the_endpoint(
    client: AsyncTestClient[Litestar], keys: Any, key: str
) -> None:
    keys.key("t-gone", "gone")
    await keys.revoke("gone")
    answered = await client.post("/mcp", json=INIT, headers={**HEADERS, "Authorization": f"Bearer {key}"})
    assert (answered.status_code, answered.headers["www-authenticate"]) == (
        HTTP_401_UNAUTHORIZED,
        'Bearer error="invalid_token"',
    )


@pytest.mark.parametrize("key", [{}, {"Authorization": "Bearer t-ana"}], ids=["nobody", "a-key"])
async def test_server_a_tool_route_answers_the_engine_only(
    client: AsyncTestClient[Litestar], key: dict[str, str]
) -> None:
    """A tool's route reached straight over HTTP, with or without a key, is refused: only the MCP engine calls it."""
    answered = await client.post("/mcp/tools/probe_echo", json={"text": "x"}, headers=key)
    assert (answered.status_code, answered.json()["detail"]) == (
        403,
        "an MCP tool: called through the MCP endpoint only",
    )
