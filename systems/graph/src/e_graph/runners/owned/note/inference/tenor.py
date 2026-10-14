"""runners.owned.note.inference.tenor: the note's term in days and years, under both day-count conventions."""

from datetime import date
from typing import Any

from e_graph.instrument.state import RunState
from e_graph.logic.models import Call


async def run(state: RunState, call: Call) -> dict[str, Any]:
    """Pricing to maturity: the true days, ACT/365, and the bond-market 30/360."""
    terms = state.context.extract["EXT-terms"]
    start, end = date.fromisoformat(terms["pricing_date"]), date.fromisoformat(terms["maturity_date"])
    thirty_360 = (end.year - start.year) * 360 + (end.month - start.month) * 30 + min(end.day, 30) - min(start.day, 30)
    return {
        "days_act": (end - start).days,
        "years_act365": round((end - start).days / 365, 4),
        "years_30360": round(thirty_360 / 360, 4),
    }
