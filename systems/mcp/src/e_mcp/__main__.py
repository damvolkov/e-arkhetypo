"""e_mcp: `python -m e_mcp` / `e-mcp` — serve the MCP app with granian (Rust ASGI) on loopback."""

from granian.constants import Interfaces
from granian.server import Server

from e_mcp.config.mcp import McpSettings


def main() -> None:
    st = McpSettings.load()
    Server(
        "e_mcp.main:assemble",
        address=st.host,
        port=st.port,
        interface=Interfaces.ASGI,
        factory=True,
        workers=1,
        log_access=False,
    ).serve()


if __name__ == "__main__":
    main()
