"""e_api.mcp.registry: the MCP door's whole surface — every tool route, resource by resource, one tuple `main` registers
like the API's routers and the MCP lifespan reads into the engine's registry. A new tool is a new handler in its
resource's module, never an edit here but its module's line."""

from typing import Final

from litestar.handlers import HTTPRouteHandler

from e_api.mcp.tools import health, user

ROUTES: Final[tuple[HTTPRouteHandler, ...]] = (*health.ROUTES, *user.ROUTES)
