"""runners.owned.note.audit.dates: the calendar's order — pricing, issue, observations, payments, maturity, each after the one before."""

from datetime import date
from typing import Any

from e_graph.instrument.state import RunState
from e_graph.logic.models import Call


async def run(state: RunState, call: Call) -> dict[str, Any]:
    """Every ordering the note promises, checked on the ISO dates; each broken one is named."""
    terms, schedule = state.context.extract["EXT-terms"], state.context.extract["EXT-schedule"]
    pricing, issue, maturity = (
        date.fromisoformat(terms[key]) for key in ("pricing_date", "issue_date", "maturity_date")
    )
    rows = schedule["observations"]
    violations = [
        label
        for label, held in (
            (f"pricing {pricing} after issue {issue}", pricing <= issue),
            (f"issue {issue} after maturity {maturity}", issue <= maturity),
            (
                f"maturity {maturity} before final observation {schedule['final_observation']}",
                date.fromisoformat(schedule["final_observation"]) <= maturity,
            ),
            (
                "an observation outside issue and maturity",
                all(issue < date.fromisoformat(r["observation_date"]) <= maturity for r in rows),
            ),
            (
                "a payment outside issue and maturity",
                all(issue < date.fromisoformat(r["payment_date"]) <= maturity for r in rows),
            ),
        )
        if not held
    ]
    return {"holds": not violations, "violations": violations}
