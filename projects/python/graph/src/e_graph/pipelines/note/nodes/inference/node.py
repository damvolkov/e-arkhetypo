"""pipelines.note.nodes.inference.node: the note's inference, run by the orchestrator."""

from typing import Any

from e_graph.instrument.state import RunState
from e_graph.models.section import Section


async def node_inference(state: RunState) -> dict[str, Any]:
    """Derive the term, the coupon, the drag, the ladder and the scenarios."""
    return await state.infra.orchestrator.node(Section.INFERENCE, state)
