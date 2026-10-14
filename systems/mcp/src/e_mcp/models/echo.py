"""e_mcp.models.echo: what the demo tool answers — a frozen msgspec value, rendered to plain JSON by the surface."""

import msgspec


class Echo(msgspec.Struct, frozen=True, kw_only=True):
    """The server's echo of a message, with the port it answered from."""

    message: str = ""
    port: int = 0
