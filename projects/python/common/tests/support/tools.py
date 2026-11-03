"""tests/support/tools: a small door of tools, as a service declares them — the app the MCP engine is tested on.

Four tools of four accesses (`echo` anyone, `whoami` an account, `wipe` the admin, `refuse` raising a 404), each a
Litestar route made by `McpTool.route`; `build` is the app over an auth engine: the token middleware, the guard on
every router, the tool routes behind the internal guard, the MCP endpoint on `/mcp`, its server run for the app's life."""

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, Final

import msgspec
from litestar import Litestar, Request
from litestar.datastructures import State
from litestar.exceptions import NotFoundException
from litestar.middleware import DefineMiddleware
from litestar.params import JSONBody  # noqa: TC002 — litestar resolves the handlers' annotations at run time
from litestar.router import Router

from e_infra.infra.auth.guard import OPT, guard
from e_infra.infra.auth.middleware import TokenMiddleware
from e_infra.infra.auth.models import Access, Caller
from e_infra.infra.mcp.guard import internal
from e_infra.infra.mcp.models import McpTool
from e_infra.infra.mcp.mount import McpMount
from e_infra.infra.mcp.registry import McpRegistry
from e_infra.infra.mcp.server import McpServer

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from litestar.handlers import HTTPRouteHandler

    from e_infra.engines.auth import AuthEngine

BASE: Final[str] = "http://127.0.0.1:8000"
HOSTS: Final[tuple[str, ...]] = ("127.0.0.1:8000", "localhost:8000")
NO: Final[dict[str, Any]] = {"dependencies": {}, "exception_handlers": {}}


class EchoArgs(msgspec.Struct, frozen=True, kw_only=True):
    """The text to echo, this many times."""

    text: str
    times: int = 1


class NoArgs(msgspec.Struct, frozen=True, kw_only=True):
    """A tool that takes nothing."""


class Echoed(msgspec.Struct, frozen=True, kw_only=True):
    """What `echo` answers."""

    text: str


class Who(msgspec.Struct, frozen=True, kw_only=True):
    """The caller a tool saw."""

    name: str
    role: str


async def echo(data: JSONBody[EchoArgs]) -> Echoed:
    return Echoed(text=data.text * data.times)


async def whoami(data: JSONBody[NoArgs], request: Request[Caller, None, Any]) -> Who:
    return Who(name=request.user.name, role=request.user.role)


async def wipe(data: JSONBody[NoArgs]) -> list[str]:
    return ["everything"]


async def refuse(data: JSONBody[NoArgs]) -> None:
    raise NotFoundException(detail="nothing here")


ECHO: Final = McpTool(name="probe_echo", title="Echo", description="Echo the text, `times` times.")
WHOAMI: Final = McpTool(name="probe_whoami", title="Who am I", description="The account that is asking.")
WIPE: Final = McpTool(
    name="probe_wipe", title="Wipe", description="Wipe everything.", read_only=False, destructive=True
)
REFUSE: Final = McpTool(name="probe_refuse", title="Refuse", description="Always answers 404.")

ROUTES: Final[tuple[HTTPRouteHandler, ...]] = (
    ECHO.route(Access.ANONYMOUS, **NO)(echo),
    WHOAMI.route(Access.USER, **NO)(whoami),
    WIPE.route(Access.ADMIN, **NO)(wipe),
    REFUSE.route(Access.ANONYMOUS, **NO)(refuse),
)


def build(engine: AuthEngine) -> Litestar:
    """The app: both guards, the token middleware over `engine`, the tools and the endpoint, the server run with it."""
    server = McpServer(
        McpRegistry(ROUTES),
        name="probe",
        version="0",
        instructions="A probe.",
        hosts=HOSTS,
        origins=[f"http://{host}" for host in HOSTS],
    )

    @asynccontextmanager
    async def serving(_app: Litestar) -> AsyncGenerator[None]:
        async with server.run():
            yield

    return Litestar(
        route_handlers=[
            Router(path="/", route_handlers=list(ROUTES), guards=[internal, guard]),
            Router(
                path="/",
                route_handlers=[McpMount(lambda app: app.state["mcp"]).route("/mcp")],
                opt=OPT[Access.ANONYMOUS],
                guards=[guard],
            ),
        ],
        middleware=[DefineMiddleware(TokenMiddleware, locate=lambda app: app.state["auth"])],
        state=State({"mcp": server, "auth": engine}),
        lifespan=[serving],
    )
