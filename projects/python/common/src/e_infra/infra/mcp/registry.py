"""infra/mcp/registry: the tools an MCP door declares, read off their routes — explicit, checked once at startup.

Each route carries its `MCPTool` (`models.TOOL`), answers POST and takes its arguments as one msgspec Struct, `data`:
the Struct's fields are the tool's arguments, its JSON Schema — required fields, defaults, formats — what a client is
told; a Struct answer gives the tool's output schema too. A name declared twice, a route without its tool, a method
other than POST or arguments that are not a Struct refuse the start."""

from types import MappingProxyType
from typing import TYPE_CHECKING, Any, cast, get_type_hints

import msgspec

from e_infra.infra.errors import MCPRegistryError
from e_infra.infra.logger import logger
from e_infra.infra.mcp.models import TOOL, MCPEntry

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping

    from litestar.handlers import HTTPRouteHandler


class MCPRegistry:
    """The tools by name, each the route that answers it."""

    __slots__ = ("_entries",)

    def __init__(self, routes: Iterable[HTTPRouteHandler]) -> None:
        entries = [self._common_entry(route) for route in routes]
        names = [entry.tool.name for entry in entries]
        twice = sorted({name for name in names if names.count(name) > 1})
        _ = twice and self._common_refuse(f"tools declared twice: {', '.join(twice)}")
        self._entries: Mapping[str, MCPEntry] = MappingProxyType({entry.tool.name: entry for entry in entries})
        logger.debug("mcp registry read", tools=sorted(self._entries))

    ##### PRIVATE #####

    @staticmethod
    def _common_refuse(message: str) -> None:
        logger.error("mcp registry refused", reason=message)
        raise MCPRegistryError(message)

    @staticmethod
    def _common_schema(kind: type[msgspec.Struct]) -> dict[str, Any]:
        """The Struct's JSON Schema as an object at the root, its nested definitions beside it."""
        schema = msgspec.json.schema(kind)
        defined: dict[str, Any] = schema.get("$defs", {})
        root = defined.pop(schema["$ref"].rsplit("/", 1)[1])
        return {**root, **({"$defs": defined} if defined else {})}

    @classmethod
    def _common_entry(cls, route: HTTPRouteHandler) -> MCPEntry:
        hints = get_type_hints(route.fn)
        data, answer = hints.get("data"), hints.get("return")
        match (route.opt.get(TOOL), route.http_methods, data):
            case (None, _, _):
                cls._common_refuse(f"route {route.handler_name}: no tool in its options")
            case (_, methods, _) if methods != {"POST"}:
                cls._common_refuse(f"route {route.handler_name}: a tool answers POST, not {sorted(methods)}")
            case (_, _, kind) if not (isinstance(kind, type) and issubclass(kind, msgspec.Struct)):
                cls._common_refuse(f"route {route.handler_name}: a tool's arguments are one Struct, `data`")
            case _:
                pass
        structured = isinstance(answer, type) and issubclass(answer, msgspec.Struct)
        return MCPEntry(
            tool=route.opt[TOOL],
            path=next(iter(route.paths)),
            arguments=cls._common_schema(cast("type[msgspec.Struct]", data)),
            answer=cls._common_schema(answer) if structured else None,
        )

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
