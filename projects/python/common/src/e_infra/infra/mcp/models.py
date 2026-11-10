"""infra/mcp/models: the vocabulary of the MCP engine — a tool as a route declares it, and a call's answer.

A tool as the registry reads it, a call's answer as the bridge brings it back. No SDK type here: `server` alone speaks
the protocol.

A tool is a Litestar route whose options carry its `MCPTool` under `TOOL`, at its access; `MCPTool.route` is that route,
on `PATH/<name>`: POST, out of the OpenAPI spec, its options the access, the tool, and authentication left out — the
caller rides in from the MCP endpoint's own request, resolved there once."""

from collections.abc import Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

import msgspec
from litestar import post

from e_infra.infra.auth.guard import ACCESS
from e_infra.infra.auth.middleware import EXCLUDED
from e_infra.infra.payload import JSON

if TYPE_CHECKING:
    from litestar.di import Provide
    from litestar.handlers import HTTPRouteHandler
    from litestar.types import ExceptionHandlersMap

    from e_infra.infra.auth.models import Access

### the route option a tool is declared under, and where every tool's route answers.
TOOL: Final[str] = "mcp"
PATH: Final[str] = "/mcp/tools"


class MCPTool(msgspec.Struct, frozen=True, kw_only=True):
    """What a client is told of a tool: its name, title and description, and the protocol's hints."""

    name: str
    title: str
    description: str
    read_only: bool = True
    destructive: bool = False

    def opt(self, access: Access) -> Mapping[str, Access | bool | MCPTool]:
        """The route's options for this tool at `access`: kept out of authentication, the caller handed in."""
        return MappingProxyType({ACCESS: access, EXCLUDED: True, TOOL: self})

    def route(
        self,
        access: Access,
        *,
        dependencies: Mapping[str, Provide],
        exception_handlers: ExceptionHandlersMap,
    ) -> HTTPRouteHandler:
        """The tool's route, to decorate its handler with: `PATH/<name>`, POST, its options, its chains, its refusals."""
        return post(
            f"{PATH}/{self.name}",
            name=f"mcp.{self.name}",
            opt=dict(self.opt(access)),
            dependencies=dict(dependencies),
            exception_handlers=dict(exception_handlers),
            include_in_schema=False,
            status_code=200,
        )


class MCPEntry(msgspec.Struct, frozen=True, kw_only=True):
    """A tool as the registry holds it: what it is, where its route answers, its arguments' and answer's JSON Schema."""

    tool: MCPTool
    path: str
    arguments: Mapping[str, JSON]
    answer: Mapping[str, JSON] | None = None


class MCPAnswer(msgspec.Struct, frozen=True, kw_only=True):
    """A tool's answer: its text, its value when it is an object, or the refusal as the route gave it."""

    text: str
    value: Mapping[str, JSON] | None = None
    error: bool = False
