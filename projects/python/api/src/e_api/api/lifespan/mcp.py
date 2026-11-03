"""api.lifespan.mcp: the MCP engine built over the door's tools, its session manager run for the app's life.

The tools are the door's routes (`mcp/registry`), read into the engine's registry (`infra/mcp`): what a client lists,
what the bridge calls. The server is built here, after the engines the tools reach exist, and lands under `system.mcp`
(`mcp/state`), where the endpoint's mount forwards to it. Who is asking is the token middleware's, before the server sees
the request; each tool admits the caller at its own access. The transport refuses any Host or Origin that is not this
service's: MCP_HOSTS and MCP_ORIGINS say which, and empty they are this port on `127.0.0.1` and `localhost`.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from importlib.metadata import version

from litestar import Litestar

from e_api.api.state import AppState
from e_api.mcp.instructions import INSTRUCTIONS
from e_api.mcp.registry import ROUTES
from e_api.mcp.state import McpState
from infra.logger import logger
from infra.mcp.registry import McpRegistry
from infra.mcp.server import McpServer
from infra.settings import settings as st


@asynccontextmanager
async def lifespan(app: Litestar) -> AsyncGenerator[None]:
    """Build the server over the door's tools, run its session manager, then mount the section under `system.mcp`."""
    hosts = tuple(st.mcp.hosts) or (f"127.0.0.1:{st.app.port}", f"localhost:{st.app.port}")
    origins = tuple(st.mcp.origins) or tuple(f"http://{host}" for host in hosts)
    server = McpServer(
        McpRegistry(ROUTES),
        name="e-api",
        version=version("e-api"),
        instructions=INSTRUCTIONS,
        hosts=hosts,
        origins=origins,
    )
    async with server.run():
        AppState.of(app).system.mcp = McpState(server=server)
        logger.info("mcp ready", tools=len(server.registry), step="START")
        yield
