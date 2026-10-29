"""pipelines.filing.nodes.ingest.node: the filing's entry: read the 10-K page by page."""

from typing import Any

from e_graph.instrument.state import RunState
from e_graph.models.section import Section


async def node_ingest(state: RunState) -> dict[str, Any]:
    """Read the filing page by page."""
    return await state.logic.orchestrator.node(Section.INGEST, state)
