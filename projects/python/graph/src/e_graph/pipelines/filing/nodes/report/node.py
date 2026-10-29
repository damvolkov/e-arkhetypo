"""pipelines.filing.nodes.report.node: the facts in one record."""

from typing import Any

from e_graph.instrument.state import RunState
from e_graph.models.section import Section


async def node_report(state: RunState) -> dict[str, Any]:
    """Gather the facts and the audits' verdict in one record."""
    return await state.logic.orchestrator.node(Section.REPORT, state)
