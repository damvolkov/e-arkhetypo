"""nodes.extract.node: pull the values out of the canonical text — the join of the parallel pair."""

import asyncio
import re
from typing import Any, cast

from e_graph.instrument.state import RunState


async def node_extract(state: RunState) -> dict[str, Any]:
    """Pull the amount out of the canonical text."""
    await asyncio.sleep(cast("float", state.context.get("pace", 0.0)))
    state.context.attempts = cast("int", state.context.get("attempts", 0)) + 1
    match state.context.get("fail", False):
        case True:
            msg = "extraction failed on purpose"
            raise RuntimeError(msg)
        case _:
            found = re.search(r"\d+(?:\.\d+)?", cast("str", state.context.canonical).split("total")[-1])
            state.context.amount = found.group() if found else ""
            ### a dict report: `summary` fills its slot, every other key travels as the output's `extra`.
            return {
                "summary": f"attempt {state.context.attempts}: amount {state.context.amount or 'missing'}",
                "attempt": state.context.attempts,
                "amount": state.context.amount,
            }
