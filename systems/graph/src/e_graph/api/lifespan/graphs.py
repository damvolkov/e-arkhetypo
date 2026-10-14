"""api.lifespan.graphs: every pipeline built once by the registry — the graph singletons every run shares.

The registry sweeps `pipelines/` for builders (a new module is picked up on its own) and builds each
one: fresh graph, declaration, compile. A broken declaration (a node off contract, a router with
unknown targets, two builders in one module) fails the boot, never a request. The built graphs mount
as `system.graphs` — the same mapping `RunState.graphs` hands every node — and are never rebuilt."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from litestar import Litestar

from core.logger import logger
from e_graph.api.state import AppState
from e_graph.pipelines.base import PipelineRegistry


@asynccontextmanager
async def lifespan(app: Litestar) -> AsyncIterator[None]:
    """Build every discovered pipeline once, then mount them by name under `system.graphs`."""
    graphs = await PipelineRegistry().build()
    AppState.of(app).system.graphs = graphs
    logger.info("graphs ready", graphs=list(graphs), step="START")
    yield
