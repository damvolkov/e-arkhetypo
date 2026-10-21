"""pipelines.note.nodes.report.node: the note's report, run by the orchestrator."""

from typing import Any

from e_graph.instrument.state import RunState
from e_graph.models.section import Section


async def node_report(state: RunState) -> dict[str, Any]:
    """Gather the term sheet, the classification and every verdict in one record."""
    return await state.infra.orchestrator.node(Section.REPORT, state)
