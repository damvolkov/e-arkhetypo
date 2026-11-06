"""api.lifespan.engines: build the engines over the providers' ports, then survey every provider once.

The concern owns its subtree as a typed section: `EnginesState` holds each engine by its role. The engines keep
references and configuration only, so this concern owns no resource to close. `auth` is the engine every door asks who
is calling (the token middleware reads it off the sealed graph); with a secret set its admin account is made here, no
key issued. `health` surveys every provider at once (each under PING_TIMEOUT, so the whole takes the slowest): right
after they open — one log event each, never a failed start — and on every `GET /ready`. Required are `store`, the
provider the app's records live on, and `auth`, without which no key resolves; every other provider is reported, never
blocking."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Final

from litestar import Litestar

from e_api.api.lifespan.providers import ProvidersState
from e_api.api.state import AppState
from e_api.engines.auth import AuthEngine
from e_api.engines.health import HealthEngine
from e_api.infra.logger import logger
from e_api.infra.settings import settings as st

### the providers a ready service cannot do without; a role not here is optional.
REQUIRED: Final[frozenset[str]] = frozenset({"store", "auth"})


##### SECTION #####
@dataclass(frozen=True, slots=True)
class EnginesState:
    """The typed engines section: `auth`, accounts and keys; `health`, every provider surveyed together, the required
    ones deciding readiness."""

    auth: AuthEngine
    health: HealthEngine


@asynccontextmanager
async def lifespan(app: Litestar) -> AsyncGenerator[None]:
    """Build the engines over the mounted providers, mount them under `system.engines`, log the startup survey."""
    system = AppState.of(app).system
    providers: ProvidersState = system.providers
    auth = AuthEngine(providers.auth, secret=st.AUTH_SECRET, ttl=st.AUTH_TTL, admin=st.AUTH_ADMIN)
    engines = EnginesState(auth=auth, health=HealthEngine(providers.named, REQUIRED, st.PING_TIMEOUT))
    system.engines = engines
    admin = (await engines.auth.ensure()).owner if st.AUTH_SECRET else "closed"
    logger.info("auth ready", admin=admin, ttl=str(st.AUTH_TTL or "never"), step="START")
    _ = [
        (logger.info if verdict.ok else logger.warning)(
            "provider health", provider=verdict.name, ok=verdict.ok, required=verdict.required,
            latency_ms=verdict.latency, reason=verdict.reason, step="START",
        )
        for verdict in await engines.health.survey()
    ]  # fmt: skip
    yield
