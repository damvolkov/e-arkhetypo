"""tests/unit/e_api/mcp/refusals: the table of domain errors a tool refuses with — empty until a service adds one, and
copied by every tool route so no route mutates the shared one."""

from e_api.mcp.refusals import REFUSALS
from e_api.mcp.registry import ROUTES


async def test_refusals_hold_no_row_until_a_service_adds_one() -> None:
    assert dict(REFUSALS) == {}


async def test_refusals_are_copied_by_each_tool_route() -> None:
    assert all(route.exception_handlers is not REFUSALS for route in ROUTES)
