"""api.lifespan.infra: the one-time load of the shared infra singletons, mirrored as a typed graph section.

`settings` and `logger` are `LazyProxy`s in the materialized infra: nothing loads at import, the first
attribute access pays for the load exactly once per process. This lifespan *is* that first access —
the rest of the chain may then reach `st` and `logger` through a plain global import with zero startup
cost — and it deposits the loaded pair under `system.shared` for consumers that prefer the graph.
Both roads reach the same singleton: the section is the same object the module-level proxy names."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from litestar import Litestar
from structlog.typing import BindableLogger

from e_api.api.state import AppState
from infra.logger import logger
from infra.proxy import LazyProxy
from infra.settings import Settings
from infra.settings import settings as st


##### SECTION #####
@dataclass(frozen=True, slots=True)
class SharedState:
    """The typed shared section: exactly the two singletons every other concern may depend on.

    An explicit two-field section beats a generic bag (the decision, documented): consumers want
    `state.shared.settings.app.app_env`, not a stringly-typed lookup — and `Settings` is `Any`-typed by
    design in infra (dynamic composition), so a fancier wrapper could not add static strength anyway.
    The values held are the lazy singletons themselves: their delegation surface *is* the
    `Settings`/`BindableLogger` contract, and the load this lifespan triggered already ran."""

    settings: Settings
    logger: LazyProxy[BindableLogger]


@asynccontextmanager
async def lifespan(app: Litestar) -> AsyncGenerator[None]:
    """Force the lazy infra load once, then mirror the pair into `system.shared` before yielding."""
    system = AppState.of(app).system
    ### first attribute access builds and caches each singleton: app_env loads settings, this log line configures structlog.
    logger.info("shared ready", env=st.app.app_env, step="START")
    system.shared = SharedState(settings=st, logger=logger)
    yield
