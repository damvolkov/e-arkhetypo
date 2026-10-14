"""e_mcp.config.mcp: the server's knobs — MCP_* in the environment or `.env`, through the materialized composer."""

from pathlib import Path
from typing import ClassVar

from core.settings.base import BaseSettings, Secret


class McpSettings(BaseSettings, frozen=True):
    """Where the server listens and who may enter: loopback address, port, optional bearer token."""

    env_prefix: ClassVar[str] = "MCP_"
    env_file: ClassVar[Path] = Path(".env")

    host: str = "127.0.0.1"
    port: int = 45200
    token: Secret | None = None
