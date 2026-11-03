"""tests/unit/e_api/mcp/tools/health: liveness and readiness as tools, under both handshakes — any caller's."""

from dataclasses import fields
from typing import TYPE_CHECKING, Final

import pytest

from e_api.api.lifespan.providers import ProvidersState
from support.mcp import MODES, call

if TYPE_CHECKING:
    from support.mcp import Connect

### the roles are the section's fields: a provider the export drops leaves this list with it.
ROLES: Final[tuple[str, ...]] = tuple(each.name for each in fields(ProvidersState))


@pytest.mark.parametrize("mode", MODES)
async def test_health_alive(connect: Connect, mode: str) -> None:
    assert await call(connect, "api_health", {}, mode=mode) == {"status": "ok"}


@pytest.mark.parametrize("mode", MODES)
async def test_health_status_surveys_every_provider(connect: Connect, mode: str) -> None:
    answer = await call(connect, "api_status", {}, mode=mode)
    verdicts = {each["name"]: each for each in answer["providers"]}
    assert (answer["ready"], sorted(verdicts), verdicts["store"]["required"], verdicts["auth"]["required"]) == (
        True,
        sorted(ROLES),
        True,
        True,
    )


async def test_health_status_lists_the_tools(connect: Connect) -> None:
    async with connect() as mcp:
        tools = {tool.name: tool for tool in (await mcp.list_tools()).tools}
    assert sorted(tools) == [
        "api_health",
        "api_status",
        "api_user_create",
        "api_user_delete",
        "api_user_list",
        "api_user_read",
        "api_user_update",
    ]
    assert tools["api_status"].output_schema is not None
