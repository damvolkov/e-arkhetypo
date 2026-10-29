"""pipelines.doc.nodes.report.node: serialize the record in the requested format and confirm delivery."""

from typing import Any, cast

import anyio

from e_graph.instrument.state import RunState
from e_graph.models.section import Section


async def node_report(state: RunState) -> dict[str, Any]:
    """Serialize the record in the requested format (`format`, JSON by default) and confirm it."""
    await anyio.sleep(cast("float", state.context.get("pace", 0.0)))
    report = await state.logic.orchestrator.node(Section.REPORT, state)
    ### the section's own words for the canvas: what was delivered, and how.
    serial = state.context.report["REP-serial"]
    return {**report, "summary": f"delivered {len(serial['text'])} bytes as {serial['format']}"}
