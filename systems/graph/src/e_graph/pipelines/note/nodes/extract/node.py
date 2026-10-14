"""pipelines.note.nodes.extract.node: the note's extract, run by the orchestrator."""

from typing import Any

from e_graph.instrument.state import RunState
from e_graph.models.section import Section


async def node_extract(state: RunState) -> dict[str, Any]:
    """Read the cover's terms, the date schedule and the money."""
    return await state.infra.orchestrator.node(Section.EXTRACT, state)
