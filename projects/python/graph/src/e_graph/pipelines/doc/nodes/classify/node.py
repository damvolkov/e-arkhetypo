"""pipelines.doc.nodes.classify.node: decide the document type, in parallel with normalize."""

from typing import Any, cast

import anyio

from e_graph.instrument.state import RunState
from e_graph.models.section import Section


async def node_classify(state: RunState) -> dict[str, Any]:
    """Decide the document type, and with it the schema and rules."""
    await anyio.sleep(cast("float", state.context.get("pace", 0.0)))
    return await state.infra.orchestrator.node(Section.CLASSIFY, state)
