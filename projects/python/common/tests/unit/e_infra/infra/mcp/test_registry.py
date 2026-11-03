"""tests/unit/e_infra/infra/mcp/registry: the tools read off their routes — each a POST taking one Struct, named once —
and the start refused for a route that cannot be a tool."""

import pytest
from litestar import get, post

from e_infra.infra.auth.models import Access
from e_infra.infra.errors import McpRegistryError
from e_infra.infra.mcp.registry import McpRegistry
from support.tools import ECHO, NO, echo, wipe


async def bare() -> dict[str, str]:
    return {}


def test_registry_reads_a_tool() -> None:
    (entry,) = McpRegistry([ECHO.route(Access.ANONYMOUS, **NO)(echo)])
    assert (
        entry.path,
        entry.arguments["required"],
        entry.arguments["properties"]["times"],
        entry.answer is not None,
        entry.tool.read_only,
    ) == ("/mcp/tools/probe_echo", ["text"], {"type": "integer", "default": 1}, True, True)


def test_registry_is_a_mapping_of_its_tools() -> None:
    registry = McpRegistry([ECHO.route(Access.ANONYMOUS, **NO)(echo)])
    assert ("probe_echo" in registry, "probe_ghost" in registry, len(registry), registry["probe_echo"].tool) == (
        True,
        False,
        1,
        ECHO,
    )


def test_registry_a_list_answer_has_no_output_schema() -> None:
    (entry,) = McpRegistry([ECHO.route(Access.ADMIN, **NO)(wipe)])
    assert entry.answer is None


@pytest.mark.parametrize(
    ("routes", "message"),
    [
        (
            lambda: [ECHO.route(Access.ANONYMOUS, **NO)(echo), ECHO.route(Access.USER, **NO)(echo)],
            "declared twice: probe_echo",
        ),
        (lambda: [post("/plain")(echo)], "no tool in its options"),
        (lambda: [get("/mcp/tools/probe_echo", opt=dict(ECHO.opt(Access.ANONYMOUS)))(bare)], "answers POST"),
        (lambda: [ECHO.route(Access.ANONYMOUS, **NO)(bare)], "arguments are one Struct"),
    ],
    ids=["twice", "untooled", "method", "arguments"],
)
def test_registry_refuses(routes: object, message: str) -> None:
    with pytest.raises(McpRegistryError, match=message):
        McpRegistry(routes())  # ty: ignore[call-non-callable]
