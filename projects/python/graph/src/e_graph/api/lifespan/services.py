"""api.lifespan.services: assemble the engines that travel with the app — crypto, telemetry, processors, the agent.

Crypto and the instrument's telemetry (over the provider the adapters lifespan opened) are pure
in-process objects. The agnostic agent is a singleton with a lifecycle: its client pool opens lazily
on the first call to each endpoint and closes here, when the app stops.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from litestar import Litestar

from core.logger import logger
from core.settings import settings as st
from e_graph.api.state import AppState
from e_graph.instrument.state import ProcessorsState
from e_graph.instrument.telemetry import InstrumentTelemetry
from e_graph.logic.agent import AgnosticAgent
from e_graph.logic.orchestrator.core import OrchestratorCore
from ops.crypto import Crypto
from processors.doc import DocProcessor


@asynccontextmanager
async def lifespan(app: Litestar) -> AsyncGenerator[None]:
    """Assemble the engines that travel with the app: crypto, the instrument's telemetry and the agent."""
    system = AppState.of(app).system
    system.crypto = Crypto(st.crypto)
    ### the instrument is vendor-free: it is handed the app's provider (here, the OTel adapter) and traces through it.
    system.telemetry = InstrumentTelemetry(system.adapters.telemetry)
    ### readers over the adapters: documents through liteparse and the docling edge, hybrid by page.
    system.processors = ProcessorsState(doc=DocProcessor(system.adapters.docling))
    ### the DARTS engine: one orchestrator for every pipeline, each pipeline's specs discovered on first use.
    system.orchestrator = OrchestratorCore()
    async with AgnosticAgent() as agent:
        system.agent = agent
        logger.info("services ready", step="START")
        yield
    logger.info("services closed", step="STOP")
