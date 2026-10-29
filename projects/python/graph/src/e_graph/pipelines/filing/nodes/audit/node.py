"""pipelines.filing.nodes.audit.node: hold what was read to the statements' own identities."""

from typing import Any

from e_graph.instrument.state import RunState
from e_graph.models.section import Section


async def node_audit(state: RunState) -> dict[str, Any]:
    """Hold the figures read to the statements' identities."""
    return await state.logic.orchestrator.node(Section.AUDIT, state)
