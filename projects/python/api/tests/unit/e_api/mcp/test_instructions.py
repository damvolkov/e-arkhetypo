"""tests/unit/e_api/mcp/instructions: what the server tells a client about itself stays true to the tools it serves."""

import pytest

from e_api.infra.mcp.models import TOOL
from e_api.mcp.instructions import INSTRUCTIONS
from e_api.mcp.registry import ROUTES

NAMES = sorted(route.opt[TOOL].name for route in ROUTES)


@pytest.mark.parametrize("name", NAMES)
async def test_instructions_name_every_tool(name: str) -> None:
    assert name in INSTRUCTIONS


async def test_instructions_name_the_key_header() -> None:
    assert "Authorization: Bearer" in INSTRUCTIONS
