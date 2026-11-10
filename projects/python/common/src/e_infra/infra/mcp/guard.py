"""infra/mcp/guard: a tool's route answers the MCP engine only — the bridge marks its requests, no client can.

The mark is a scope key no client can send; anything else reaching a tool's path is refused before its access is read."""

from typing import TYPE_CHECKING, Final

from litestar.exceptions import PermissionDeniedException

from e_infra.infra.logger import logger

if TYPE_CHECKING:
    from litestar.handlers import BaseRouteHandler

    from e_infra.infra.auth.middleware import Connection

### the scope key the bridge sets on the requests it makes: ASGI scopes are the server's, never a client's.
MARK: Final[str] = "mcp.bridged"


async def internal(connection: Connection, _handler: BaseRouteHandler) -> None:
    """Through the MCP endpoint, or refused."""
    match connection.scope.get(MARK):
        case True:
            return
        case _:
            logger.warning("mcp tool route reached directly", path=connection.url.path)
            raise PermissionDeniedException(detail="an MCP tool: called through the MCP endpoint only")
