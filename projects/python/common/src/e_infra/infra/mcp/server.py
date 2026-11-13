"""infra/mcp/server: the protocol — the official SDK's low-level server and its Streamable HTTP manager.

The only module of the package that imports the SDK's server: an SDK upgrade touches this file and no other.

The SDK negotiates every protocol version a client speaks (the legacy `initialize` handshake and the stateless one),
checks Host and Origin, keeps the sessions; `tools/list` is the registry's, `tools/call` the bridge's. The server is
an ASGI app: the MCP endpoint's mount hands it the request whole."""

from typing import TYPE_CHECKING, Protocol

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request

from e_infra.infra.logger import logger
from e_infra.infra.mcp.bridge import MCPBridge

if TYPE_CHECKING:
    from collections.abc import Sequence
    from contextlib import AbstractAsyncContextManager

    from starlette.types import Receive, Scope, Send

    from e_infra.infra.mcp.models import MCPEntry
    from e_infra.infra.mcp.registry import MCPRegistry


class ToolContext(Protocol):
    """What a call reads of the SDK's request context: the HTTP request its transport attached, if any."""

    @property
    def request(self) -> Request | None: ...


class MCPServer:
    """The MCP endpoint over a registry of tools: list them, call them through the app, serve the transport."""

    __slots__ = ("_bridge", "_manager", "_registry", "_server")

    def __init__(
        self,
        registry: MCPRegistry,
        *,
        name: str,
        version: str,
        instructions: str,
        hosts: Sequence[str],
        origins: Sequence[str],
    ) -> None:
        self._registry = registry
        self._bridge = MCPBridge()
        self._server = Server(
            name,
            version=version,
            instructions=instructions,
            on_list_tools=self._common_list_tools,
            on_call_tool=self._call_tool,
        )
        security = TransportSecuritySettings(allowed_hosts=list(hosts), allowed_origins=list(origins))
        self._manager = StreamableHTTPSessionManager(app=self._server, json_response=True, security_settings=security)
        logger.debug("mcp server built", name=name, tools=len(registry), hosts=list(hosts))

    ##### PRIVATE #####

    @staticmethod
    def _common_list_tool(entry: MCPEntry) -> types.Tool:
        tool = entry.tool
        hints = types.ToolAnnotations(
            title=tool.title, read_only_hint=tool.read_only, destructive_hint=tool.destructive, open_world_hint=False
        )
        return types.Tool(
            name=tool.name,
            title=tool.title,
            description=tool.description,
            input_schema=dict(entry.arguments),
            output_schema=None if entry.answer is None else dict(entry.answer),
            annotations=hints,
        )

    async def _common_list_tools(
        self, _ctx: ToolContext, _params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[self._common_list_tool(entry) for entry in self._registry])

    async def _call_tool(self, ctx: ToolContext, params: types.CallToolRequestParams) -> types.CallToolResult:
        ### the HTTP request the transport attached: the endpoint's, its scope the caller's.
        match (params.name in self._registry, ctx.request):
            case (False, _):
                return self._call_refused(f"no tool {params.name!r}: tools/list names them")
            case (_, Request() as request):
                entry = self._registry[params.name]
                answer = await self._bridge.call(request.scope, entry.path, params.arguments or {})
                _ = answer.error and logger.warning("mcp tool refused", tool=params.name, reason=answer.text)
                return types.CallToolResult(
                    content=[types.TextContent(type="text", text=answer.text)],
                    structured_content=None if answer.value is None else dict(answer.value),
                    is_error=answer.error,
                )
            case _:
                return self._call_refused("a tool is called over HTTP, through the MCP endpoint")

    @staticmethod
    def _call_refused(text: str) -> types.CallToolResult:
        logger.warning("mcp call refused", reason=text)
        return types.CallToolResult(content=[types.TextContent(type="text", text=text)], is_error=True)

    ############################################################

    ##### PUBLIC #####

    @property
    def registry(self) -> MCPRegistry:
        return self._registry

    @property
    def instructions(self) -> str:
        return self._server.instructions or ""

    def run(self) -> AbstractAsyncContextManager[None]:
        """The session manager, for the app's life: entered by the lifespan that builds the server."""
        return self._manager.run()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        ### the SDK speaks Starlette's ASGI types: the mount hands the request over typed as its contract.
        await self._manager.handle_request(scope, receive, send)
