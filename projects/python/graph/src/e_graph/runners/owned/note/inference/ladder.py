"""runners.owned.note.inference.ladder: every date the note can be called and what each rung pays."""

from typing import Any

from e_graph.instrument.state import RunState
from e_graph.logic.models import Call


async def run(state: RunState, call: Call) -> dict[str, Any]:
    """Each observation that can kick the note out, paying principal plus the quarter's coupon."""
    terms = state.context.extract["EXT-terms"]
    schedule = state.context.extract["EXT-schedule"]
    payout = terms["denomination"] + terms["coupon"]["quarterly_payment"]
    return {
        "ladder": [
            {"date": row["observation_date"], "payout": payout}
            for row in schedule["observations"][:-1]
            if row["observation_date"] != schedule["final_observation"]
        ]
    }
