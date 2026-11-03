"""api.router.health: liveness and readiness.

`/health` answers without touching the state, even while backends are down; `/ready` surveys every provider at once
through the health engine (`api/lifespan/services`): 200 when every required one answers, 503 otherwise, each
provider's verdict in the body."""

from typing import Final

from litestar import Response, get
from litestar.di import NamedDependency, Provide
from litestar.handlers import HTTPRouteHandler
from litestar.status_codes import HTTP_200_OK, HTTP_503_SERVICE_UNAVAILABLE

from e_graph.api.deps import DepKey, system
from engines.health import ProviderHealth
from infra.state import State


async def health() -> dict[str, str]:
    """Liveness probe — no state access, must answer even while backends are down."""
    return {"status": "ok"}


async def ready(system: NamedDependency[State]) -> Response[list[ProviderHealth]]:
    """Readiness probe — every provider surveyed, the required ones decide."""
    verdicts: tuple[ProviderHealth, ...] = await system.infra.engines.health.survey()
    answered = all(verdict.ok for verdict in verdicts if verdict.required)
    return Response(list(verdicts), status_code=HTTP_200_OK if answered else HTTP_503_SERVICE_UNAVAILABLE)


READY_DEPS: Final[dict[str, Provide]] = {DepKey.SYSTEM.value: Provide(system, sync_to_thread=False)}

ROUTES: tuple[HTTPRouteHandler, ...] = (
    get("/health", name="health")(health),
    get("/ready", name="ready", dependencies=READY_DEPS)(ready),
)
