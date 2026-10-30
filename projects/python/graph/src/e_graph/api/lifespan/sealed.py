"""api.lifespan.sealed: last link of the chain — type `infra`, seal the graph.

Every concern has written its singleton by now, the infrastructure's under `system.infra` (`providers`, `engines`,
`processors`, `graphs`): the open node is retyped as the `InfraState` section every run reads, the same objects in the same place,
beside the branches the instrument and the logic mounted themselves. Sealing freezes the shape of what lives with the app; the contexts store inside
`system.instrument` keeps taking and dropping runs."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from litestar import Litestar

from e_graph.api.state import AppState
from e_graph.instrument.state import InfraState


@asynccontextmanager
async def lifespan(app: Litestar) -> AsyncGenerator[None]:
    """Last link of the chain: `infra` typed, and the graph read-only from here on."""
    system = AppState.of(app).system
    ### the open node the lifespans wrote is replaced by its typed twin: one home per object, never two.
    built = system.infra
    system.infra = InfraState(
        providers=built.providers, engines=built.engines, processors=built.processors, graphs=built.graphs
    )
    system.seal()
    yield
