"""e_mcp.config.mcp: the server's knobs — MCP_* in the environment or `.env`."""

from pydantic_settings import SettingsConfigDict

from infra.settings.base import BaseSettings, Secret


class McpSettings(BaseSettings):
    """Where the server listens and who may enter: loopback address, port, optional bearer token."""

    model_config = SettingsConfigDict(env_prefix="MCP_", env_file=".env", extra="ignore", frozen=True)

    host: str = "127.0.0.1"
    port: int = 45200
    token: Secret | None = None
