"""pipelines.note.nodes.ingest.node: the note's ingest, run by the orchestrator."""

from typing import Any

from e_graph.instrument.state import RunState
from e_graph.models.section import Section


async def node_ingest(state: RunState) -> dict[str, Any]:
    """The note read page by page."""
    return await state.infra.orchestrator.node(Section.INGEST, state)
