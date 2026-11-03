"""e_api.mcp.refusals: a domain error as the tool's refusal — the API's own exceptions answer as they do, a tool adds none.

A refusal is the route's `detail`, which the MCP engine hands back as the tool's error text. The user records raise
Litestar's own `NotFoundException`; a domain error of a service becomes a row here, mapped to the status it earns."""

from typing import Final

from litestar.types import ExceptionHandlersMap

### every tool route's exception handlers, copied by each route (`McpTool.route`): Litestar takes a mutable map.
REFUSALS: Final[ExceptionHandlersMap] = {}
