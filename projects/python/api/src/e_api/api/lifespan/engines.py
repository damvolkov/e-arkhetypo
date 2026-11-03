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
from engines.auth import AuthEngine
from engines.health import HealthEngine
from infra.logger import logger
from infra.settings import settings as st

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
    conf = st.engines.auth
    engines = EnginesState(auth=AuthEngine(providers.auth, conf), health=HealthEngine(providers.named, REQUIRED))
    system.engines = engines
    admin = (await engines.auth.ensure()).owner if conf.secret else "closed"
    logger.info("auth ready", admin=admin, ttl=str(conf.ttl or "never"), step="START")
    _ = [
        (logger.info if verdict.ok else logger.warning)(
            "provider health", provider=verdict.name, ok=verdict.ok, required=verdict.required,
            latency_ms=verdict.latency, reason=verdict.reason, step="START",
        )
        for verdict in await engines.health.survey()
    ]  # fmt: skip
    yield
