"""runners.owned.note.inference.drag: the fee drag — price above the issuer's own estimate of worth."""

from typing import Any

from e_graph.instrument.state import RunState
from e_graph.logic.models import Call


async def run(state: RunState, call: Call) -> dict[str, Any]:
    """The gap per note between offering price and estimated value, and its share of the price."""
    terms = state.context.extract["EXT-terms"]
    gap = terms["offering_price"] - terms["estimated_value"]
    return {"per_note": round(gap, 6), "share": round(gap / terms["offering_price"], 6)}
