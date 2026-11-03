"""infra/mcp/mount: the MCP endpoint as a Litestar mount — the route exists at build, the server only at run.

The mount finds the server on each request through `locate`, the door's own way to its branch."""

from typing import TYPE_CHECKING, cast

from litestar import Litestar, asgi

### at run time: Litestar reads the forwarder's signature when it builds the route.
from litestar.types import Receive, Scope, Send  # noqa: TC002

from e_infra.infra.logger import logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from litestar.handlers import ASGIRouteHandler

    from e_infra.infra.mcp.server import MCPServer


class MCPMount:
    """The endpoint's route, forwarding every request on its path to the server `locate` finds."""

    __slots__ = ("_locate",)

    def __init__(self, locate: Callable[[Litestar], MCPServer]) -> None:
        self._locate = locate

    ##### PRIVATE #####

    async def _route_forward(self, scope: Scope, receive: Receive, send: Send) -> None:
        logger.debug("mcp mount forward", path=scope["path"])
        await self._locate(Litestar.from_scope(scope))(cast("Scope", {**scope, "root_path": ""}), receive, send)

    ############################################################

    ##### PUBLIC #####

    def route(self, path: str, **opt: object) -> ASGIRouteHandler:
        """The mount on `path`, exactly: a catch-all would shadow the app's own path-parameter routes."""
        return asgi(path, name="mcp", is_mount=True, copy_scope=True, opt=opt)(self._route_forward)
