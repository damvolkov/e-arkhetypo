"""api.lifespan.sealed: last link of the chain — seal the graph once every concern has written its subtree."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from litestar import Litestar

from e_api.api.state import AppState


@asynccontextmanager
async def lifespan(app: Litestar) -> AsyncGenerator[None]:
    """Last link of the chain: from here on the graph is read-only for every request."""
    AppState.of(app).system.seal()
    yield
