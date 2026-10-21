"""runners.owned.note.audit.schedule: the observations run quarterly and monotonic — each gap in months, each payment between its observation and the next."""

from datetime import date
from itertools import pairwise
from typing import Annotated, Any

import msgspec

from core.struct import CheckedStruct
from e_graph.instrument.state import RunState
from e_graph.logic.models import Call


class Args(CheckedStruct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """`months`: the spacing expected between observations; `spread`: the days either way a holiday may push it."""

    months: Annotated[int, msgspec.Meta(ge=1, le=12)] = 3
    spread: Annotated[int, msgspec.Meta(ge=0, le=45)] = 21

    def gaps(self, rows: list[dict[str, str]]) -> list[str]:
        """The names of what breaks: a payment not after its observation, a step not months wide within the spread."""
        dates = [(date.fromisoformat(row["observation_date"]), date.fromisoformat(row["payment_date"])) for row in rows]
        return [
            complaint
            for (then, paid), (later, _) in pairwise(dates)
            for complaint, held in (
                (f"payment {paid} not after {then}", paid > then),
                (f"payment {paid} not before the next observation {later}", paid < later),
                (
                    f"{then} to {later} is not {self.months} months within {self.spread} days",
                    abs((later - then).days - 30.4 * self.months) <= self.spread,
                ),
            )
            if not held
        ] + [f"last payment {paid} not after {then}" for then, paid in dates[-1:] if paid <= then]


async def run(state: RunState, call: Call) -> dict[str, Any]:
    """The count of observations and the names of every spacing or order that fails; holds when nothing is named."""
    observations = state.context.extract["EXT-schedule"]["observations"]
    gaps = call.args.gaps(observations)
    return {"holds": not gaps, "count": len(observations), "gaps": gaps}
