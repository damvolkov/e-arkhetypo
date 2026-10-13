"""nodes.ingest.node: the demo pipeline's entry — receive the document and fingerprint it."""

import asyncio
import hashlib
from typing import cast

from e_graph.instrument.state import RunState


async def node_ingest(state: RunState) -> str:
    """Receive the document and fingerprint it."""
    await asyncio.sleep(cast("float", state.context.get("pace", 0.0)))
    document = cast("str", state.context.get("document", "invoice 42 · total 1250.00 EUR"))
    state.context.document = document
    state.context.digest = hashlib.blake2b(document.encode(), digest_size=8).hexdigest()
    return f"registered {state.context.digest}"
