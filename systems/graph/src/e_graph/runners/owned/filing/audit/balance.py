"""runners.owned.filing.audit.balance: the balance sheet's identity — assets equal liabilities plus equity."""

from typing import Annotated, Any

import msgspec

from core.struct import CheckedStruct
from e_graph.instrument.state import RunState
from e_graph.logic.models import Call


class Args(CheckedStruct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """`tolerance`: the share of assets the gap may reach — noncontrolling interests sit outside equity."""

    tolerance: Annotated[float, msgspec.Meta(ge=0, le=1)] = 0.05


async def run(state: RunState, call: Call) -> dict[str, Any]:
    """The gap between assets and liabilities plus equity, its share of assets, and whether it is tolerable."""
    sheet = state.context.extract["EXT-balance"]
    gap = sheet["total_assets"] - sheet["total_liabilities"] - sheet["equity"]
    ### no assets read is no balance at all: the gap is the whole of it.
    share = abs(gap) / abs(sheet["total_assets"]) if sheet["total_assets"] else 1.0
    return {"gap": gap, "share": share, "holds": share <= call.args.tolerance}
