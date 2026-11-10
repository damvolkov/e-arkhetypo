"""infra/config/mcp: the MCP door — where the endpoint answers and which Host and Origin the transport accepts."""

from collections.abc import Sequence

from e_infra.infra.config.base import BaseSettings


##### SETTINGS #####
class McpSettings(BaseSettings):
    """The MCP door: a foreign Host or Origin is refused (421)."""

    ### where the endpoint answers.
    MCP_PATH: str = "/mcp"
    ### JSON lists of `host:port` and origins; empty, the composition root derives them from APP_PORT.
    MCP_HOSTS: Sequence[str] = ()
    MCP_ORIGINS: Sequence[str] = ()
