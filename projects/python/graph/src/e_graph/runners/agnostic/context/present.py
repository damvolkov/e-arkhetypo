"""runners.agnostic.context.present: the integrity gate — the outputs a spec reads exist and are not empty."""

from typing import Annotated

import msgspec

from core.struct import CheckedStruct
from e_graph.instrument.state import RunState
from e_graph.logic.models import Address, Call


class Args(CheckedStruct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """`needs`: the outputs that must be there, as `<section>/<spec>` addresses in the run's context."""

    needs: Annotated[tuple[Address, ...], msgspec.Meta(min_length=1)]


async def check(state: RunState, call: Call) -> bool:
    """Whether every output the spec reads was written and holds something."""
    return all(
        getattr(state.context, section).get(spec)
        for section, _, spec in (need.partition("/") for need in call.args.needs)
    )
