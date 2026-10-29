"""runners.owned.note.inference.coupon: the quarterly coupon per note as the rate accrues it, held to what the note states."""

from typing import Annotated, Any

import msgspec

from e_graph.instrument.state import RunState
from e_graph.logic.models import Call
from infra.struct import CheckedStruct


class Args(CheckedStruct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """`tolerance`: the dollars per note the printed payment and the accrual may be apart — rounding aside."""

    tolerance: Annotated[float, msgspec.Meta(gt=0, le=1)] = 0.005


async def run(state: RunState, call: Call) -> dict[str, Any]:
    """Rate over four, times the stated principal — and whether the printed payment agrees within tolerance."""
    terms = state.context.extract["EXT-terms"]
    coupon, principal = terms["coupon"], terms["denomination"]
    annual = coupon["rate_percent"] / 100 * principal
    quarterly = annual / 4
    return {
        "annual_per_note": round(annual, 6),
        "quarterly_computed": round(quarterly, 6),
        "quarterly_stated": coupon["quarterly_payment"],
        "agrees": abs(quarterly - coupon["quarterly_payment"]) <= call.args.tolerance,
    }
