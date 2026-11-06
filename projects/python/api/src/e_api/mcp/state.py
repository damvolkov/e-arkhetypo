"""e_api.mcp.state: the MCP door's typed branch, `system.mcp` — the engine's server over the door's registry of tools,
built and run for the app's life by `api/lifespan/mcp`, read by the endpoint's mount."""

from dataclasses import dataclass

from e_api.infra.mcp.server import MCPServer


@dataclass(frozen=True, slots=True)
class MCPState:
    """The MCP section: the server the endpoint forwards to, its registry the door's tools."""

    server: MCPServer
