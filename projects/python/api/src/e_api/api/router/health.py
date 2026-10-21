"""api.router.health: liveness, plus the oauth chain exercised by a real (tiny) consumer."""

from typing import Final

from authlib.integrations.starlette_client import OAuth
from litestar import get
from litestar.di import NamedDependency, Provide
from litestar.handlers import HTTPRouteHandler

from e_api.api.deps import DepKey, graph, oauth, registered_providers


async def health() -> dict[str, str]:
    """Liveness probe — no graph access, must answer even while backends are down."""
    return {"status": "ok"}


async def providers(oauth: NamedDependency[OAuth]) -> dict[str, list[str]]:
    """Identities registered with authlib — empty until OAUTH__* is configured."""
    return {"providers": registered_providers(oauth)}


##### CHAINS — endpoint-local wiring: enum-owned keys, .value only at the litestar edge #####
OAUTH_DEPS: Final[dict[str, Provide]] = {
    DepKey.GRAPH.value: Provide(graph, sync_to_thread=False),
    DepKey.OAUTH.value: Provide(oauth, sync_to_thread=False),
}

ROUTES: tuple[HTTPRouteHandler, ...] = (
    get("/health", name="health")(health),
    get("/oauth/providers", name="oauth.providers", dependencies=OAUTH_DEPS)(providers),
)
