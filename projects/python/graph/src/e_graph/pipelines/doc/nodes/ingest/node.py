"""pipelines.doc.nodes.ingest.node: the pipeline's entry: receive the document and fingerprint it."""

from typing import Any, cast

import anyio

from e_graph.instrument.state import RunState
from e_graph.models.section import Section


async def node_ingest(state: RunState) -> dict[str, Any]:
    """Receive the document and fingerprint it."""
    await anyio.sleep(cast("float", state.context.get("pace", 0.0)))
    return await state.infra.orchestrator.node(Section.INGEST, state)
