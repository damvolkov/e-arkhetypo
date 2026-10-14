"""e_mcp.mcp.tools: the logic as MCP tools — thin, typed, every answer a plain JSON value.

Each method is one tool; the composition root registers them by name. Keep the surface dumb: decisions
belong to `logic`, I/O to `adapters`."""

from typing import Any

import msgspec
from beartype import beartype

from e_mcp.logic.echo import greet
from e_mcp.models.echo import Echo


@beartype
class EchoTools:
    """The template's MCP surface over the echo logic."""

    __slots__ = ("_port",)

    def __init__(self, port: int) -> None:
        self._port = port

    ##### PUBLIC #####

    async def ping(self) -> dict[str, Any]:
        """Whether the server is alive, and the port it answers from."""
        return {"alive": True, "port": self._port}

    async def greet(self, name: str = "") -> dict[str, Any]:
        """A greeting for `name`; an empty name greets the world."""
        return msgspec.to_builtins(Echo(message=greet(name), port=self._port))
