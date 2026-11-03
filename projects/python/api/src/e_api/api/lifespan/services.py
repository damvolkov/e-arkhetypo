"""api.lifespan.services: assemble the engines that travel with the app.

Crypto is written into the system graph — the user records' password hashing —; it is a pure in-process object, so this
concern owns no resource to close.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from litestar import Litestar

from e_api.api.state import AppState
from infra.logger import logger
from infra.settings import settings as st
from ops.crypto import Crypto


@asynccontextmanager
async def lifespan(app: Litestar) -> AsyncGenerator[None]:
    """Assemble the engines that travel with the app: crypto."""
    AppState.of(app).system.crypto = Crypto(st.crypto)
    logger.info("services ready", step="START")
    yield
