"""api.lifespan.instrument: the instrument's branch, mounted as `system.instrument` — the tracer and the contexts store.

The instrument is vendor-free: its telemetry is handed the app's provider (the OTel adapter the adapters lifespan
opened) and traces through it. The contexts store is opened empty and survives the seal: sealing freezes the shape of
what lives with the app, never the runs that come and go — each run opens `context.<id>` and releases it when it
closes. Both are pure in-process objects: nothing to close."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from litestar import Litestar

from e_graph.api.state import AppState
from e_graph.instrument.contexts import InstrumentContexts
from e_graph.instrument.state import InstrumentState
from e_graph.instrument.telemetry import InstrumentTelemetry
from infra.logger import logger


@asynccontextmanager
async def lifespan(app: Litestar) -> AsyncGenerator[None]:
    """Build the tracer over the app's provider and the empty contexts store, then mount `system.instrument`."""
    system = AppState.of(app).system
    system.instrument = InstrumentState(
        telemetry=InstrumentTelemetry(system.adapters.telemetry), contexts=InstrumentContexts()
    )
    logger.info("instrument ready", step="START")
    yield
