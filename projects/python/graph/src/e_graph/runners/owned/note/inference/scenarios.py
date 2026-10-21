"""runners.owned.note.inference.scenarios: the payoff if the index ends each way from -60% to +40%.

A flat path: the level that holds at maturity holds on every earlier observation too, so a call happens
on the first rung whenever the level reaches the call threshold; otherwise the maturity rule pays —
principal plus the final coupon when the barrier held, principal alone at or above the downside
threshold without the barrier, and the principal marked to the index below it."""

from typing import Any, Final

from e_graph.instrument.state import RunState
from e_graph.logic.models import Call

MOVES: Final = range(-60, 41, 10)
PERCENT: Final = 100.0


async def run(state: RunState, call: Call) -> dict[str, Any]:
    """One scenario per move: level, whether it calls, whether the coupon pays, and what the holder ends with."""
    terms = state.context.extract["EXT-terms"]
    levels, principal = terms["levels"], terms["denomination"]
    coupon, initial = terms["coupon"]["quarterly_payment"], levels["initial_value"]
    return {
        "scenarios": [
            {
                "move_percent": move / 1.0,
                "final_level": round(level, 4),
                "called": called,
                "coupon_paid": called or (at_or_above and level >= levels["coupon_barrier"]),
                "payout": round(
                    principal + coupon
                    if called or (at_or_above and level >= levels["coupon_barrier"])
                    else principal
                    if at_or_above
                    else principal * level / initial,
                    4,
                ),
            }
            for move in MOVES
            for level in (initial * (1 + move / PERCENT),)
            for called in (level >= levels["call_level"],)
            for at_or_above in (level >= levels["downside_threshold"],)
        ]
    }
