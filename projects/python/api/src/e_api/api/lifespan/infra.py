"""api.lifespan.infra: the first touch of the shared logger, mirrored as a typed graph section.

`settings` was read at import (`Settings()`, once); `logger` is a `LazyProxy`: its first attribute access configures
structlog. This lifespan *is* that first access, and it deposits the logger under `system.shared` for consumers that
prefer the graph. Settings never travel on the graph: the composition root reads `st` and hands values down."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from litestar import Litestar
from structlog.typing import BindableLogger

from e_api.api.state import AppState
from e_api.infra.logger import logger
from e_api.infra.proxy import LazyProxy
from e_api.infra.settings import settings as st


##### SECTION #####
@dataclass(frozen=True, slots=True)
class SharedState:
    """The typed shared section: the logger every other concern may depend on, the lazy singleton itself."""

    logger: LazyProxy[BindableLogger]


@asynccontextmanager
async def lifespan(app: Litestar) -> AsyncGenerator[None]:
    """Touch the logger once, then mirror it into `system.shared` before yielding."""
    system = AppState.of(app).system
    ### the first attribute access configures structlog.
    logger.info("shared ready", env=st.APP_ENV, step="START")
    system.shared = SharedState(logger=logger)
    yield
