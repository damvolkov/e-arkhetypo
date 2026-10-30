"""api.router.health: liveness and readiness, plus the oauth chain exercised by a real (tiny) consumer.

`/health` touches nothing — it answers even while a backend is down; `/ready` surveys every provider at once
(`engines.health`, built by `api/lifespan/engines`): 200 when every required one answers, 503 otherwise, each provider's
verdict in the body."""

from typing import Final

from authlib.integrations.starlette_client import OAuth
from litestar import Response, get
from litestar.di import NamedDependency, Provide
from litestar.handlers import HTTPRouteHandler
from litestar.status_codes import HTTP_200_OK, HTTP_503_SERVICE_UNAVAILABLE

from e_api.api.deps import DepKey, graph, oauth, registered_providers
from engines.health import ProviderHealth
from infra.state import State


async def health() -> dict[str, str]:
    """Liveness probe — no graph access, must answer even while backends are down."""
    return {"status": "ok"}


async def ready(graph: NamedDependency[State]) -> Response[list[ProviderHealth]]:
    """Readiness probe — every provider surveyed, the required ones decide."""
    verdicts: tuple[ProviderHealth, ...] = await graph.engines.health.survey()
    answered = all(verdict.ok for verdict in verdicts if verdict.required)
    return Response(list(verdicts), status_code=HTTP_200_OK if answered else HTTP_503_SERVICE_UNAVAILABLE)


async def providers(oauth: NamedDependency[OAuth]) -> dict[str, list[str]]:
    """Identities registered with authlib — empty until OAUTH__* is configured."""
    return {"providers": registered_providers(oauth)}


##### CHAINS — endpoint-local wiring: enum-owned keys, .value only at the litestar edge #####
OAUTH_DEPS: Final[dict[str, Provide]] = {
    DepKey.GRAPH.value: Provide(graph, sync_to_thread=False),
    DepKey.OAUTH.value: Provide(oauth, sync_to_thread=False),
}

READY_DEPS: Final[dict[str, Provide]] = {DepKey.GRAPH.value: Provide(graph, sync_to_thread=False)}

ROUTES: tuple[HTTPRouteHandler, ...] = (
    get("/health", name="health")(health),
    get("/ready", name="ready", dependencies=READY_DEPS)(ready),
    get("/oauth/providers", name="oauth.providers", dependencies=OAUTH_DEPS)(providers),
)
