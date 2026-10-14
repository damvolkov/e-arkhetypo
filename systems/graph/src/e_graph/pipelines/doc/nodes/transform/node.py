"""nodes.transform.node: deterministic mapping of the extraction into the output shape."""

import asyncio
from decimal import Decimal
from typing import cast

from e_graph.instrument.state import RunState


async def node_transform(state: RunState) -> None:
    """Map the extraction into the output record."""
    await asyncio.sleep(cast("float", state.context.get("pace", 0.0)))
    state.context.record = {
        "kind": state.context.kind,
        "digest": state.context.digest,
        "amount": str(Decimal(cast("str", state.context.amount))),
    }
