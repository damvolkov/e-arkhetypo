"""api.lifespan.sealed: last link of the chain — compose `infra`, open the contexts store, seal the graph.

Every concern has written its singleton by now: they are composed into the typed `infra` section every
run reads (`state.infra.adapters`, `.agent`, `.telemetry`, `.graphs`). The contexts store is opened here
too, and survives the seal: sealing freezes the shape of what lives with the app, never the runs that
come and go — each run opens `context.<id>` and releases it when it closes."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from litestar import Litestar

from e_graph.api.state import AppState
from e_graph.instrument.state import ContextState, InfraState


@asynccontextmanager
async def lifespan(app: Litestar) -> AsyncGenerator[None]:
    """Last link of the chain: `infra` composed, `contexts` opened, and the graph read-only from here on."""
    system = AppState.of(app).system
    system.infra = InfraState(
        adapters=system.adapters,
        processors=system.processors,
        agent=system.agent,
        orchestrator=system.orchestrator,
        telemetry=system.telemetry,
        graphs=system.graphs,
    )
    system.contexts = ContextState()
    system.seal()
    yield
