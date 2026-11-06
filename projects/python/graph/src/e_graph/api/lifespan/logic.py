"""api.lifespan.logic: the logic's branch, mounted as `system.logic` — the agnostic agent and the DARTS orchestrator.

The agent is a singleton with a lifecycle: its client pool opens lazily on the first call to each endpoint and closes
here, when the app stops. The orchestrator is one for every pipeline, each pipeline's specs discovered on first use.
`agent` and `darts` read their values from `st` for every root that builds them — this lifespan and the cli."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from litestar import Litestar

from e_graph.api.state import AppState
from e_graph.infra.logger import logger
from e_graph.infra.settings import settings as st
from e_graph.logic.agent import AgnosticAgent
from e_graph.logic.models import Darts
from e_graph.logic.orchestrator.core import OrchestratorCore
from e_graph.logic.state import LogicState


##### ROOT #####
def agent() -> AgnosticAgent:
    """The agent over AGENT_* and every provider's key and base."""
    return AgnosticAgent(
        credentials=st.agent_credentials(), tiers=st.agent_tiers(), timeout=st.AGENT_TIMEOUT, retries=st.AGENT_RETRIES
    )


def darts() -> Darts:
    """The DARTS budgets, DARTS_*."""
    return Darts(
        concurrency=st.DARTS_CONCURRENCY,
        calls=st.DARTS_CALLS,
        fusion_specs=st.DARTS_FUSION_SPECS,
        fusion_tokens=st.DARTS_FUSION_TOKENS,
        timeout=st.DARTS_TIMEOUT,
    )


@asynccontextmanager
async def lifespan(app: Litestar) -> AsyncGenerator[None]:
    """Open the agent, build the orchestrator, then mount `system.logic`; the agent closes when the app stops."""
    system = AppState.of(app).system
    async with agent() as live:
        system.logic = LogicState(agent=live, orchestrator=OrchestratorCore(darts()))
        logger.info("logic ready", step="START")
        yield
    logger.info("logic closed", step="STOP")
