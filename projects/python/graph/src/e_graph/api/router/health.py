"""api.router.health: liveness and readiness.

`/health` answers without touching the state, even while backends are down; `/ready` pings every edge at once
(`api/lifespan/adapters`): 200 when every required one answers, 503 otherwise, each edge's verdict in the body."""

from typing import Final

from litestar import Response, get
from litestar.di import NamedDependency, Provide
from litestar.handlers import HTTPRouteHandler
from litestar.status_codes import HTTP_200_OK, HTTP_503_SERVICE_UNAVAILABLE

from adapters.base import AdapterPing
from e_graph.api.deps import DepKey, system
from infra.settings import settings as st
from infra.state import State


async def health() -> dict[str, str]:
    """Liveness probe — no state access, must answer even while backends are down."""
    return {"status": "ok"}


async def ready(system: NamedDependency[State]) -> Response[list[AdapterPing]]:
    """Readiness probe — every edge pinged, the required ones decide."""
    pings: tuple[AdapterPing, ...] = await system.adapters.ping(st.ping.timeout)
    answered = all(ping.ok for ping in pings if ping.required)
    return Response(list(pings), status_code=HTTP_200_OK if answered else HTTP_503_SERVICE_UNAVAILABLE)


READY_DEPS: Final[dict[str, Provide]] = {DepKey.SYSTEM.value: Provide(system, sync_to_thread=False)}

ROUTES: tuple[HTTPRouteHandler, ...] = (
    get("/health", name="health")(health),
    get("/ready", name="ready", dependencies=READY_DEPS)(ready),
)
