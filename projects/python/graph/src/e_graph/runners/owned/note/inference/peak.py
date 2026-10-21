"""runners.owned.note.inference.peak: the best and the worst total return a holder can end with."""

from datetime import date
from typing import Any, Final

from e_graph.instrument.state import RunState
from e_graph.logic.models import Call

PERCENT: Final = 100.0


async def run(state: RunState, call: Call) -> dict[str, Any]:
    """Best: the first rung of the ladder pays the quarterly coupon — its return, and how soon. Worst: the barrier breaks and the index goes to zero."""
    terms = state.context.extract["EXT-terms"]
    schedule = state.context.extract["EXT-schedule"]
    quarterly = call.inputs["INF-coupon"]["quarterly_stated"]
    first = date.fromisoformat(schedule["observations"][0]["observation_date"])
    pricing = date.fromisoformat(terms["pricing_date"])
    return {
        "best_percent": round(quarterly / terms["denomination"] * PERCENT, 6),
        "best_years": round((first - pricing).days / 365, 4),
        "worst_percent": -PERCENT,
    }
