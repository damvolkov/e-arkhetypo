"""api.lifespan.services: assemble the engines that travel with the app.

Crypto and the IdP-backed oauth registry are written into the system graph; they are pure in-process
objects, so this concern owns no resource to close.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from authlib.integrations.starlette_client import OAuth
from litestar import Litestar

from core.logger import logger
from core.settings import settings as st
from e_api.api.state import AppState
from ops.crypto import Crypto


@asynccontextmanager
async def lifespan(app: Litestar) -> AsyncGenerator[None]:
    """Assemble the engines that travel with the app: crypto and the IdP-backed oauth registry."""
    system = AppState.of(app).system
    system.crypto = Crypto(st.crypto)
    system.oauth = OAuth()
    match st.oauth.server_metadata_url:
        case "":
            ### dev mode: empty registry, the app boots without an IdP
            pass
        case url:
            system.oauth.register(
                st.oauth.oauth_name,
                client_id=st.oauth.client_id,
                client_secret=st.oauth.client_secret,
                server_metadata_url=url,
            )
    logger.info("services ready", step="START")
    yield
