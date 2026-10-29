"""api.lifespan.graphs: every pipeline built once by the registry — the graph singletons every run shares.

The registry sweeps `pipelines/` for builders (a new module is picked up on its own) and builds each
one: fresh graph, declaration, compile. A broken declaration (a node off contract, a router with
unknown targets, two builders in one module) fails the boot, never a request. The built graphs mount
as `system.infra.graphs` — the same mapping `RunState.infra.graphs` hands every node — and are never rebuilt."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from litestar import Litestar

from e_graph.api.state import AppState
from e_graph.pipelines.base import PipelineRegistry
from infra.logger import logger


@asynccontextmanager
async def lifespan(app: Litestar) -> AsyncGenerator[None]:
    """Build every discovered pipeline once, then mount them by name under `system.infra.graphs`."""
    graphs = await PipelineRegistry().build()
    AppState.of(app).system.infra.graphs = graphs
    logger.info("graphs ready", graphs=list(graphs), step="START")
    yield
