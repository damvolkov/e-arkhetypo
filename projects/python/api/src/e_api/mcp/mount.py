"""e_api.mcp.mount: the MCP endpoint, MCP_PATH (`/mcp`) — the engine's mount, finding the server on the sealed graph's MCP
branch on each request (the route exists before the server does). Any caller may reach it: the token middleware resolved
who, each tool admits them at its own access."""

from litestar.handlers import ASGIRouteHandler

from e_api.api.state import AppState
from e_api.infra.mcp.mount import MCPMount


def routes(*, path: str) -> tuple[ASGIRouteHandler, ...]:
    """The endpoint's route on `path` (MCP_PATH, read by the root); the server it forwards to is the MCP lifespan's,
    found on the sealed graph on each request."""
    return (MCPMount(lambda app: AppState.of(app).system.mcp.server).route(path),)
