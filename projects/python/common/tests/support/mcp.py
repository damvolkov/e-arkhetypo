"""tests/support/mcp: the MCP endpoint as a client meets it — the SDK's own client over HTTP, in process (an ASGI
transport) on the running app, each connection the headers a harness sends and the handshake it speaks (`legacy`, the
`initialize` of every client to date, or `auto`, the stateless discovery). Conftests re-export `connect`; tests import
`call` (a tool's answer) and `refused` (the error a tool gives)."""

from collections.abc import AsyncGenerator, Callable, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import TYPE_CHECKING, Any, Final, cast

import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

if TYPE_CHECKING:
    from litestar import Litestar
    from litestar.testing import AsyncTestClient

type Connect = Callable[..., AbstractAsyncContextManager[Client]]

MODES: Final[tuple[str, ...]] = ("legacy", "auto")
BASE: Final[str] = "http://127.0.0.1:8000"


@pytest.fixture
def connect(app: Litestar, client: AsyncTestClient[Litestar]) -> Connect:
    """One SDK client on the running app's `/mcp`, with the headers and the handshake given; `client` keeps the
    lifespans running."""
    _ = client

    @asynccontextmanager
    async def opened(headers: Mapping[str, str] | None = None, mode: str = "auto") -> AsyncGenerator[Client]:
        ### Litestar's ASGI app, typed by Litestar; the transport types it Starlette's way: the same contract.
        transport = httpx2.ASGITransport(app=cast("Any", app))
        async with (
            httpx2.AsyncClient(transport=transport, base_url=BASE, headers=dict(headers or {})) as http,
            Client(streamable_http_client(f"{BASE}/mcp", http_client=http), mode=mode) as mcp,
        ):
            yield mcp

    return opened


async def call(
    connect: Connect, tool: str, arguments: dict[str, Any], headers: Mapping[str, str] | None = None, mode: str = "auto"
) -> Any:
    """The tool's structured answer, the call not refused."""
    async with connect(headers, mode) as mcp:
        result = await mcp.call_tool(tool, arguments)
    assert not result.is_error, result.content
    return result.structured_content


async def refused(
    connect: Connect, tool: str, arguments: dict[str, Any], headers: Mapping[str, str] | None = None, mode: str = "auto"
) -> str:
    """The error text of a call the tool refuses."""
    async with connect(headers, mode) as mcp:
        result = await mcp.call_tool(tool, arguments)
    assert result.is_error, result.content
    return "".join(getattr(block, "text", "") for block in result.content)
