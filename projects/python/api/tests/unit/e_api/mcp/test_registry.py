"""tests/unit/e_api/mcp/registry: the door's whole surface, held to what a client was told — the same tools, titles,
descriptions, access, arguments, required ones and hints (`resources/mcp/surface.json`). A change to the surface is a
deliberate edit of that file, never a side effect."""

import json
from typing import TYPE_CHECKING

from e_api.mcp.registry import ROUTES
from infra.auth.guard import ACCESS
from infra.mcp.models import TOOL
from infra.mcp.registry import McpRegistry

if TYPE_CHECKING:
    from pytest_resources import Resources


def test_registry_surface_is_unchanged(resources: Resources) -> None:
    told = {tool["name"]: tool for tool in json.loads((resources.path / "mcp" / "surface.json").read_text())}
    access = {route.opt[TOOL].name: route.opt[ACCESS].value for route in ROUTES}
    now = {
        entry.tool.name: {
            "name": entry.tool.name,
            "title": entry.tool.title,
            "description": entry.tool.description,
            "access": access[entry.tool.name],
            "annotations": {
                "destructive_hint": entry.tool.destructive,
                "open_world_hint": False,
                "read_only_hint": entry.tool.read_only,
            },
            "arguments": sorted(entry.arguments.get("properties", {})),
            "required": sorted(entry.arguments.get("required", [])),
        }
        for entry in McpRegistry(ROUTES)
    }
    assert now == told
