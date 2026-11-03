"""infra/mcp/server: the protocol — the official SDK's low-level server and its Streamable HTTP manager.

The only module of the package that imports the SDK's server: an SDK upgrade touches this file and no other.

The SDK negotiates every protocol version a client speaks (the legacy `initialize` handshake and the stateless one),
checks Host and Origin, keeps the sessions; `tools/list` is the registry's, `tools/call` the bridge's. The server is
an ASGI app: the MCP endpoint's mount hands it the request whole."""

from typing import TYPE_CHECKING, Any, cast

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings

from e_infra.infra.logger import logger
from e_infra.infra.mcp.bridge import McpBridge

if TYPE_CHECKING:
    from collections.abc import Sequence
    from contextlib import AbstractAsyncContextManager

    from litestar.types import Receive, Scope, Send

    from e_infra.infra.mcp.models import McpEntry
    from e_infra.infra.mcp.registry import McpRegistry


class McpServer:
    """The MCP endpoint over a registry of tools: list them, call them through the app, serve the transport."""

    __slots__ = ("_bridge", "_manager", "_registry", "_server")

    def __init__(
        self,
        registry: McpRegistry,
        *,
        name: str,
        version: str,
        instructions: str,
        hosts: Sequence[str],
        origins: Sequence[str],
    ) -> None:
        self._registry = registry
        self._bridge = McpBridge()
        self._server = Server(
            name,
            version=version,
            instructions=instructions,
            on_list_tools=self._list_tools,
            on_call_tool=self._call_tool,
        )
        security = TransportSecuritySettings(allowed_hosts=list(hosts), allowed_origins=list(origins))
        self._manager = StreamableHTTPSessionManager(app=self._server, json_response=True, security_settings=security)
        logger.debug("mcp server built", name=name, tools=len(registry), hosts=list(hosts))

    ##### PRIVATE #####

    @staticmethod
    def _list_tool(entry: McpEntry) -> types.Tool:
        tool = entry.tool
        hints = types.ToolAnnotations(
            title=tool.title, read_only_hint=tool.read_only, destructive_hint=tool.destructive, open_world_hint=False
        )
        return types.Tool(
            name=tool.name,
            title=tool.title,
            description=tool.description,
            input_schema=entry.arguments,
            output_schema=entry.answer,
            annotations=hints,
        )

    async def _list_tools(self, _ctx: Any, _params: Any) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[self._list_tool(entry) for entry in self._registry])

    async def _call_tool(self, ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
        ### the HTTP request the transport attached: the endpoint's, its scope the caller's.
        request: Any = getattr(ctx, "request", None)
        match (params.name in self._registry, request):
            case (False, _):
                return self._call_refused(f"no tool {params.name!r}: tools/list names them")
            case (_, None):
                return self._call_refused("a tool is called over HTTP, through the MCP endpoint")
            case _:
                entry = self._registry[params.name]
                answer = await self._bridge.call(request.scope, entry.path, params.arguments or {})
                _ = answer.error and logger.warning("mcp tool refused", tool=params.name, reason=answer.text)
                return types.CallToolResult(
                    content=[types.TextContent(type="text", text=answer.text)],
                    structured_content=answer.value,
                    is_error=answer.error,
                )

    @staticmethod
    def _call_refused(text: str) -> types.CallToolResult:
        logger.warning("mcp call refused", reason=text)
        return types.CallToolResult(content=[types.TextContent(type="text", text=text)], is_error=True)

    ############################################################

    ##### PUBLIC #####

    @property
    def registry(self) -> McpRegistry:
        return self._registry

    @property
    def instructions(self) -> str:
        return self._server.instructions or ""

    def run(self) -> AbstractAsyncContextManager[None]:
        """The session manager, for the app's life: entered by the lifespan that builds the server."""
        return self._manager.run()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        ### the same ASGI contract, typed by Litestar on this side and by Starlette on the SDK's.
        await self._manager.handle_request(cast("Any", scope), cast("Any", receive), cast("Any", send))
