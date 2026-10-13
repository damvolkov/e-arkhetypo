"""api.lifespan.core: the one-time load of the shared core singletons, mirrored as a typed graph section.

`settings` and `logger` are `LazyProxy`s in the materialized core: nothing loads at import, the first
attribute access pays for the load exactly once per process. This lifespan *is* that first access —
the rest of the chain may then reach `st` and `logger` through a plain global import with zero startup
cost — and it deposits the loaded pair under `system.core` for consumers that prefer the graph.
Both roads reach the same singleton: the section is the same object the module-level proxy names."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from litestar import Litestar
from structlog.typing import BindableLogger

from core.logger import logger
from core.proxy import LazyProxy
from core.settings import Settings
from core.settings import settings as st
from e_graph.api.state import AppState


##### SECTION #####
@dataclass(frozen=True, slots=True)
class CoreState:
    """The typed core section: exactly the two singletons every other concern may depend on.

    An explicit two-field section beats a generic bag (the decision, documented): consumers want
    `state.core.settings.app.app_env`, not a stringly-typed lookup — and `Settings` is `Any`-typed by
    design in core (dynamic composition), so a fancier wrapper could not add static strength anyway.
    The values held are the lazy singletons themselves: their delegation surface *is* the
    `Settings`/`BindableLogger` contract, and the load this lifespan triggered already ran."""

    settings: Settings
    logger: LazyProxy[BindableLogger]


@asynccontextmanager
async def lifespan(app: Litestar) -> AsyncIterator[None]:
    """Force the lazy core load once, then mirror the pair into `system.core` before yielding."""
    system = AppState.of(app).system
    ### first attribute access builds and caches each singleton: app_env loads settings, this log line configures structlog.
    logger.info("core ready", env=st.app.app_env, step="START")
    system.core = CoreState(settings=st, logger=logger)
    yield
