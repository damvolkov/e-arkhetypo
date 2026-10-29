"""api.lifespan.sealed: last link of the chain — compose `infra`, seal the graph.

Every concern has written its singleton by now: the infrastructure is composed into the typed `infra` section every
run reads (`state.infra.adapters`, `.processors`, `.graphs`), beside the branches the instrument and the logic
mounted themselves. Sealing freezes the shape of what lives with the app; the contexts store inside
`system.instrument` keeps taking and dropping runs."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from litestar import Litestar

from e_graph.api.state import AppState
from e_graph.instrument.state import InfraState


@asynccontextmanager
async def lifespan(app: Litestar) -> AsyncGenerator[None]:
    """Last link of the chain: `infra` composed, and the graph read-only from here on."""
    system = AppState.of(app).system
    system.infra = InfraState(adapters=system.adapters, processors=system.processors, graphs=system.graphs)
    system.seal()
    yield
