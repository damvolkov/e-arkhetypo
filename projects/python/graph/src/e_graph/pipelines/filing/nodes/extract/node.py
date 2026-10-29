"""pipelines.filing.nodes.extract.node: the cover, the income statement and the balance sheet, read by the agent in one fused call."""

from typing import Any

from e_graph.instrument.state import RunState
from e_graph.models.section import Section


async def node_extract(state: RunState) -> dict[str, Any]:
    """Read the cover and the statements' headline figures."""
    return await state.logic.orchestrator.node(Section.EXTRACT, state)
