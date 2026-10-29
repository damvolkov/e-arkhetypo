"""pipelines.note.nodes.audit.node: the note's audit, run by the orchestrator."""

from typing import Any

from e_graph.instrument.state import RunState
from e_graph.models.section import Section


async def node_audit(state: RunState) -> dict[str, Any]:
    """Hold the facts to their standards and the prose to the numbers."""
    return await state.logic.orchestrator.node(Section.AUDIT, state)
