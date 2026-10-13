"""api.router.health: liveness — answers without touching the state, even while backends are down."""

from litestar import get
from litestar.handlers import HTTPRouteHandler


async def health() -> dict[str, str]:
    """Liveness probe — no state access, must answer even while backends are down."""
    return {"status": "ok"}


ROUTES: tuple[HTTPRouteHandler, ...] = (get("/health", name="health")(health),)
