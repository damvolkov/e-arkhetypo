"""pipelines.doc.nodes.extract.node: pull the amount out of the canonical text — the join of the parallel pair."""

from typing import Any, cast

import anyio

from e_graph.instrument.state import RunState
from e_graph.models.section import Section


async def node_extract(state: RunState) -> dict[str, Any]:
    """Pull the amount out of the canonical text."""
    await anyio.sleep(cast("float", state.context.get("pace", 0.0)))
    report = await state.logic.orchestrator.node(Section.EXTRACT, state)
    ### the section's own words for the canvas: which pass, which amount — the specs' statuses travel beside.
    found = state.context.extract["EXT-amount"]
    return {**report, "summary": f"attempt {found['attempt']}: amount {found['amount'] or 'missing'}"}
