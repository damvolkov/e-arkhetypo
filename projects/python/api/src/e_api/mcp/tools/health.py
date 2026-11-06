"""e_api.mcp.tools.health: liveness and readiness as tools — the twin of `api/router/health`. Read-only, any caller's."""

from typing import Final

from litestar.di import NamedDependency
from litestar.handlers import HTTPRouteHandler
from litestar.params import JSONBody

from e_api.api.router import health as router
from e_api.infra.auth.models import Access
from e_api.infra.mcp.models import MCPTool
from e_api.infra.state import State
from e_api.mcp.models import NoArgs, Status
from e_api.mcp.refusals import REFUSALS

##### TOOLS — what a client is told #####
HEALTH: Final = MCPTool(
    name="api_health",
    title="Check liveness",
    description="Whether the service is up. It touches nothing, so it answers even while a backend is down.",
)
STATUS: Final = MCPTool(
    name="api_status",
    title="Check readiness",
    description=(
        "Whether the service is ready, and every provider's verdict: its name, whether a ready service needs it, "
        "whether it answers, how long it took (ms) and why not. Ready means every required provider answers."
    ),
)


##### HANDLERS #####
async def alive(data: JSONBody[NoArgs]) -> dict[str, str]:  # noqa: ARG001 — the registry reads a tool's arguments off `data`
    return await router.health()


async def status(data: JSONBody[NoArgs], graph: NamedDependency[State]) -> Status:  # noqa: ARG001 — as above
    verdicts = await graph.engines.health.survey()
    return Status(ready=all(verdict.ok for verdict in verdicts if verdict.required), providers=list(verdicts))


##### ROUTES #####
ROUTES: tuple[HTTPRouteHandler, ...] = (
    HEALTH.route(Access.ANONYMOUS, dependencies={}, exception_handlers=REFUSALS)(alive),
    STATUS.route(Access.ANONYMOUS, dependencies=router.READY_DEPS, exception_handlers=REFUSALS)(status),
)
