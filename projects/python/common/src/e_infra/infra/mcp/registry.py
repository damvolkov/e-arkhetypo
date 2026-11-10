"""infra/mcp/registry: the tools an MCP door declares, read off their routes — explicit, checked once at startup.

Each route carries its `MCPTool` (`models.TOOL`), answers POST and takes its arguments as one msgspec Struct, `data`:
the Struct's fields are the tool's arguments, its JSON Schema — required fields, defaults, formats — what a client is
told; a Struct answer gives the tool's output schema too. A name declared twice, a route without its tool, a method
other than POST or arguments that are not a Struct refuse the start."""

from types import MappingProxyType
from typing import TYPE_CHECKING, Final, get_type_hints

import msgspec

from e_infra.infra.errors import MCPRegistryError
from e_infra.infra.logger import logger
from e_infra.infra.mcp.models import TOOL, MCPEntry, MCPTool

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping

    from litestar.handlers import HTTPRouteHandler

    from e_infra.infra.payload import JSON

### why a start is refused, each as the registry says it.
TWICE: Final[str] = "tools declared twice: {}"
NO_TOOL: Final[str] = "route {}: no tool in its options"
NOT_POST: Final[str] = "route {}: a tool answers POST, not {}"
NOT_STRUCT: Final[str] = "route {}: a tool's arguments are one Struct, `data`"


class MCPRegistry:
    """The tools by name, each the route that answers it."""

    __slots__ = ("_entries",)

    def __init__(self, routes: Iterable[HTTPRouteHandler]) -> None:
        entries = [self._common_entry(route) for route in routes]
        names = [entry.tool.name for entry in entries]
        twice = sorted({name for name in names if names.count(name) > 1})
        match twice:
            case []:
                pass
            case _:
                raise self._common_refusal(TWICE.format(", ".join(twice)))
        self._entries: Mapping[str, MCPEntry] = MappingProxyType({entry.tool.name: entry for entry in entries})
        logger.debug("mcp registry read", tools=sorted(self._entries))

    ##### PRIVATE #####

    @staticmethod
    def _common_refusal(message: str) -> MCPRegistryError:
        logger.error("mcp registry refused", reason=message)
        return MCPRegistryError(message)

    @staticmethod
    def _common_schema(kind: type[msgspec.Struct]) -> Mapping[str, JSON]:
        """The Struct's JSON Schema as an object at the root, its nested definitions beside it."""
        schema = msgspec.json.schema(kind)
        defined = schema.get("$defs", {})
        root = defined.pop(schema["$ref"].rsplit("/", 1)[1])
        return {**root, **({"$defs": defined} if defined else {})}

    @classmethod
    def _common_entry(cls, route: HTTPRouteHandler) -> MCPEntry:
        hints = get_type_hints(route.fn)
        answer = hints.get("return")
        structured = isinstance(answer, type) and issubclass(answer, msgspec.Struct)
        match (route.opt.get(TOOL), route.http_methods, hints.get("data")):
            case (tool, _, _) if not isinstance(tool, MCPTool):
                raise cls._common_refusal(NO_TOOL.format(route.handler_name))
            case (_, methods, _) if methods != {"POST"}:
                raise cls._common_refusal(NOT_POST.format(route.handler_name, sorted(methods)))
            case (MCPTool() as tool, _, type() as kind) if issubclass(kind, msgspec.Struct):
                return MCPEntry(
                    tool=tool,
                    path=next(iter(route.paths)),
                    arguments=cls._common_schema(kind),
                    answer=cls._common_schema(answer) if structured else None,
                )
            case _:
                raise cls._common_refusal(NOT_STRUCT.format(route.handler_name))

    ############################################################

    ##### PUBLIC #####

    def __getitem__(self, name: str) -> MCPEntry:
        return self._entries[name]

    def __contains__(self, name: object) -> bool:
        return name in self._entries

    def __iter__(self) -> Iterator[MCPEntry]:
        return iter(self._entries.values())

    def __len__(self) -> int:
        return len(self._entries)
