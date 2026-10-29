"""api.lifespan.logic: the logic's branch, mounted as `system.logic` — the agnostic agent and the DARTS orchestrator.

The agent is a singleton with a lifecycle: its client pool opens lazily on the first call to each endpoint and closes
here, when the app stops. The orchestrator is one for every pipeline, each pipeline's specs discovered on first use."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from litestar import Litestar

from e_graph.api.state import AppState
from e_graph.logic.agent import AgnosticAgent
from e_graph.logic.orchestrator.core import OrchestratorCore
from e_graph.logic.state import LogicState
from infra.logger import logger


@asynccontextmanager
async def lifespan(app: Litestar) -> AsyncGenerator[None]:
    """Open the agent, build the orchestrator, then mount `system.logic`; the agent closes when the app stops."""
    system = AppState.of(app).system
    async with AgnosticAgent() as agent:
        system.logic = LogicState(agent=agent, orchestrator=OrchestratorCore())
        logger.info("logic ready", step="START")
        yield
    logger.info("logic closed", step="STOP")
