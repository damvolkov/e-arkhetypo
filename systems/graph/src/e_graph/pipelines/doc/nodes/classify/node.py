"""nodes.classify.node: decide the document type, in parallel with normalize."""

import asyncio
from typing import cast

from e_graph.instrument.state import RunState


async def node_classify(state: RunState) -> str:
    """Decide the document type, and with it the schema and rules."""
    await asyncio.sleep(cast("float", state.context.get("pace", 0.0)))
    state.context.kind = "invoice" if "invoice" in cast("str", state.context.document).lower() else "unknown"
    return f"classified as {state.context.kind}"
