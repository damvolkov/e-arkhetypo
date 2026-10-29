"""pipelines.doc.nodes.normalize.node: canonical form of the document, in parallel with classify."""

from typing import Any, cast

import anyio

from e_graph.instrument.state import RunState
from e_graph.models.section import Section


async def node_normalize(state: RunState) -> dict[str, Any]:
    """Fold the document into its canonical form."""
    await anyio.sleep(cast("float", state.context.get("pace", 0.0)))
    return await state.logic.orchestrator.node(Section.NORMALIZE, state)
