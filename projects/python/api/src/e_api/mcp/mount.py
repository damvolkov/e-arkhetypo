"""e_api.mcp.mount: the MCP endpoint, MCP_PATH (`/mcp`) — the engine's mount, finding the server on the sealed graph's MCP
branch on each request (the route exists before the server does). Any caller may reach it: the token middleware resolved
who, each tool admits them at its own access."""

from litestar.handlers import ASGIRouteHandler

from e_api.api.state import AppState
from infra.config.mcp import McpSettings
from infra.mcp.mount import McpMount
from infra.settings import settings as st


def routes(settings: McpSettings | None = None) -> tuple[ASGIRouteHandler, ...]:
    """The endpoint's route on the path the settings say, read when the app is built; the server it forwards to is the
    MCP lifespan's, found on the sealed graph on each request."""
    path = (st.mcp if settings is None else settings).path
    return (McpMount(lambda app: AppState.of(app).system.mcp.server).route(path),)
