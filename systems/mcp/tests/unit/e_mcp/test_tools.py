"""The MCP surface exercised in-process: the real server, the real client, no socket."""

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import pytest
from mcp import Client
from mcp.server import MCPServer

from e_mcp.main import INSTRUCTIONS, tools
from e_mcp.mcp.tools import EchoTools

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from fakes import Connect


@pytest.fixture
def connect() -> Connect:
    @asynccontextmanager
    async def opened() -> AsyncGenerator[Client]:
        server = tools(MCPServer(name="e-mcp", instructions=INSTRUCTIONS), EchoTools(45200))
        async with Client(server) as client:
            yield client

    return opened


async def test_tools_listed(connect: Connect) -> None:
    async with connect() as client:
        listed = await client.list_tools()
        assert sorted(tool.name for tool in listed.tools) == ["greet", "ping"]


async def test_tools_ping(connect: Connect) -> None:
    async with connect() as client:
        answer = (await client.call_tool("ping", {})).structured_content
        assert (answer["alive"], answer["port"]) == (True, 45200)


@pytest.mark.parametrize(("name", "message"), [("metaxy", "hello metaxy"), ("", "hello world")], ids=["named", "world"])
async def test_tools_greet(connect: Connect, name: str, message: str) -> None:
    async with connect() as client:
        answer = (await client.call_tool("greet", {"name": name})).structured_content
        assert answer == {"message": message, "port": 45200}
