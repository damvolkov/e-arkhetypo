"""nodes.normalize.node: canonical form of the document, in parallel with classify."""

import asyncio
from typing import cast

from e_graph.instrument.state import RunState


async def node_normalize(state: RunState) -> None:
    """Fold the document into its canonical form."""
    await asyncio.sleep(cast("float", state.context.get("pace", 0.0)))
    state.context.canonical = " ".join(cast("str", state.context.document).lower().split())
