"""runners.owned.note.audit.thresholds: the protective levels stand in their order — downside, coupon barrier, call, initial value."""

from itertools import pairwise
from typing import Annotated, Any, Final

import msgspec

from core.struct import CheckedStruct
from e_graph.instrument.state import RunState
from e_graph.logic.models import Call

PERCENT: Final = 100.0


class Args(CheckedStruct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """`tolerance`: the share of the barrier the printed percentage may miss by — rounding of 75% of a level."""

    tolerance: Annotated[float, msgspec.Meta(ge=0, le=1)] = 0.01


async def run(state: RunState, call: Call) -> dict[str, Any]:
    """The four levels in the order the note needs, and whether that order — and the stated share — holds."""
    levels = state.context.extract["EXT-terms"]["levels"]
    order = [levels[key] for key in ("downside_threshold", "coupon_barrier", "call_level", "initial_value")]
    share = levels["coupon_barrier"] / levels["initial_value"] * PERCENT
    holds = all(earlier <= later for earlier, later in pairwise(order)) and (
        abs(share - levels["share_of_initial_percent"]) <= call.args.tolerance * levels["share_of_initial_percent"]
    )
    return {"holds": holds, "order": order}
