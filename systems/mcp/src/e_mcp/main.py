"""e_mcp.main: the composition root — the only module that names concretions and wires them to ports.

`assemble` is granian's factory: it reads the settings, builds the MCP server and its tool surface, and
returns the ASGI app whose lifespan runs the session manager. The bearer gate goes in front of it all;
without a token, loopback plus the Host check are the boundary."""

import logging
from collections.abc import AsyncGenerator, Callable, Mapping
from contextlib import asynccontextmanager
from typing import Any, Final

import structlog
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.routing import Mount

from core.logger import setup
from core.settings import settings as core
from e_mcp.config.mcp import McpSettings
from e_mcp.mcp.guard import TokenGuard
from e_mcp.mcp.tools import EchoTools

INSTRUCTIONS: Final = (
    "e-mcp template: an MCP server over Streamable HTTP on loopback. ping answers whether it is alive; "
    "greet echoes a name through the logic layer. Replace the echo with your domain."
)


class _ToStructlog(logging.Handler):
    """A stdlib record as a structlog event: what the MCP SDK logs through rich enters the house renderer."""

    def emit(self, record: logging.LogRecord) -> None:
        structlog.get_logger(record.name).log(
            record.levelno, record.getMessage(), exc_info=record.exc_info, stack_info=record.stack_info
        )


def quiet() -> None:
    """Route the third-party stdlib logs to structlog — before any MCPServer is built, so the SDK's
    `basicConfig` finds the root already handled and installs no RichHandler of its own."""
    if not any(isinstance(handler, _ToStructlog) for handler in logging.root.handlers):
        logging.root.addHandler(_ToStructlog())
    logging.root.setLevel(logging.INFO)


def tools(server: MCPServer, surface: EchoTools) -> MCPServer:
    """Explicit registration: every tool by its public name, nothing bound by a decorator."""
    table: Mapping[str, Callable[..., Any]] = {"ping": surface.ping, "greet": surface.greet}
    _ = [server.add_tool(fn, name=name) for name, fn in table.items()]
    return server


def assemble(st: McpSettings | None = None) -> Any:
    """The ASGI app: MCP over Streamable HTTP on loopback, the bearer gate in front when a token is set."""
    st = McpSettings.load() if st is None else st
    ### granian imports the factory in its worker process: the logger is configured where the app runs.
    setup(env=core.app.app_env)
    quiet()
    server = tools(MCPServer(name="e-mcp", instructions=INSTRUCTIONS), EchoTools(st.port))
    security = TransportSecuritySettings(
        allowed_hosts=[f"127.0.0.1:{st.port}", f"localhost:{st.port}"],
        allowed_origins=[f"http://127.0.0.1:{st.port}", f"http://localhost:{st.port}"],
    )
    mcp_app = server.streamable_http_app(json_response=True, transport_security=security, host=st.host)

    @asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncGenerator[None]:
        async with server.session_manager.run():
            yield

    app = Starlette(routes=[Mount("/", app=mcp_app)], lifespan=lifespan)
    match st.token:
        case None:
            return app
        case token:
            return TokenGuard(app, token.reveal())
