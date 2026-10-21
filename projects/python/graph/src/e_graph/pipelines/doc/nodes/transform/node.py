"""pipelines.doc.nodes.transform.node: deterministic mapping of the extraction into the output record."""

from typing import Any, cast

import anyio

from e_graph.instrument.state import RunState
from e_graph.models.section import Section


async def node_transform(state: RunState) -> dict[str, Any]:
    """Map the extraction into the output record."""
    await anyio.sleep(cast("float", state.context.get("pace", 0.0)))
    return await state.infra.orchestrator.node(Section.TRANSFORM, state)
