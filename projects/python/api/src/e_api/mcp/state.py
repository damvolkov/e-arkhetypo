"""e_api.mcp.state: the MCP door's typed branch, `system.mcp` — the engine's server over the door's registry of tools,
built and run for the app's life by `api/lifespan/mcp`, read by the endpoint's mount."""

from dataclasses import dataclass

from infra.mcp.server import McpServer


@dataclass(frozen=True, slots=True)
class McpState:
    """The MCP section: the server the endpoint forwards to, its registry the door's tools."""

    server: McpServer
