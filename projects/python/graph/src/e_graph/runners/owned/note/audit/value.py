"""runners.owned.note.audit.value: the estimated value stands under the offering price — the fee drag is the issuer's own admission."""

from typing import Any

from e_graph.instrument.state import RunState
from e_graph.logic.models import Call


async def run(state: RunState, call: Call) -> dict[str, Any]:
    """Price minus the issuer's estimate, per note; it holds when the estimate is strictly under the price."""
    terms = state.context.extract["EXT-terms"]
    gap = terms["offering_price"] - terms["estimated_value"]
    return {"gap": round(gap, 6), "holds": 0 < gap < terms["offering_price"]}
