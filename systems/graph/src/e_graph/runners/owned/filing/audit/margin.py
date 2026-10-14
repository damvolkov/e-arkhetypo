"""runners.owned.filing.audit.margin: the income statement's identity — revenue less its cost is gross profit."""

from typing import Any

from e_graph.instrument.state import RunState
from e_graph.logic.models import Call


async def run(state: RunState, call: Call) -> dict[str, Any]:
    """The gap between gross profit and revenue less cost of revenue; it holds when there is none."""
    income = state.context.extract["EXT-income"]
    gap = income["gross_profit"] - (income["revenue"] - income["cost_of_revenue"])
    return {"gap": gap, "holds": gap == 0}
