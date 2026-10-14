"""runners.agnostic.number.scale: figures read in a statement's unit, brought to units — millions to dollars."""

from typing import Annotated, Any

import msgspec

from core.struct import CheckedStruct
from e_graph.instrument.state import RunState
from e_graph.logic.models import Call


class Args(CheckedStruct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """`fields`: the figures to scale (absent or null ones stay as they are); `factor`: what one unit read is worth."""

    fields: Annotated[tuple[str, ...], msgspec.Meta(min_length=1)]
    factor: Annotated[int, msgspec.Meta(gt=0)] = 1_000_000


async def post_run(state: RunState, call: Call, output: dict[str, Any]) -> dict[str, Any]:
    """The answer with every listed figure multiplied by the factor, rounded to whole units."""
    scaled = {
        field: round(value * call.args.factor)
        for field in call.args.fields
        if isinstance(value := output.get(field), int | float)
    }
    return {**output, **scaled}
