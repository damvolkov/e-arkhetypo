"""tests/unit/e_api/mcp/state: the OST parity of the door — `system.mcp` is the section of `e_api/mcp/state.py`, its server
the engine's over the door's registry, built by the lifespan that runs it."""

from typing import TYPE_CHECKING

from e_api.mcp.instructions import INSTRUCTIONS
from e_api.mcp.registry import ROUTES
from e_api.mcp.state import McpState
from infra.mcp.server import McpServer

if TYPE_CHECKING:
    from litestar import Litestar
    from litestar.testing import AsyncTestClient


async def test_state_section_holds_the_server(client: AsyncTestClient[Litestar]) -> None:
    """The branch `mcp` is the package `e_api.mcp`: its section is that package's `state`, its server the engine's."""
    section = client.app.state.system.mcp
    assert (type(section).__module__, type(section), type(section.server), len(section.server.registry)) == (
        "e_api.mcp.state",
        McpState,
        McpServer,
        len(ROUTES),
    )
    assert section.server.instructions == INSTRUCTIONS
