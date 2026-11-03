"""infra/config/mcp: the MCP door — where the endpoint answers and which Host and Origin the transport accepts (MCP_*)."""

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from e_infra.infra.config.base import BaseSettings


class McpSettings(BaseSettings):
    """MCP_PATH — where the endpoint answers. MCP_HOSTS / MCP_ORIGINS — JSON lists of the `host:port` and the origins
    the transport accepts, a foreign one refused (421); empty, the composition root derives them from APP_PORT:
    `127.0.0.1` and `localhost`, and `http://` each of them."""

    model_config = SettingsConfigDict(env_prefix="MCP_")

    path: str = "/mcp"
    hosts: list[str] = Field(default_factory=list)
    origins: list[str] = Field(default_factory=list)
