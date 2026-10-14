"""nodes.validate.node: check the extraction, and route — back to extract for a retry, or forward."""

import asyncio
from typing import Literal, cast

from e_graph.instrument.state import RunState

ATTEMPTS: int = 2


async def node_validate(state: RunState) -> str:
    """Check the extracted amount is a number."""
    await asyncio.sleep(cast("float", state.context.get("pace", 0.0)))
    state.context.valid = cast("str", state.context.amount).replace(".", "", 1).isdigit()
    return "valid" if state.context.valid else "invalid"


def route_validate(state: RunState) -> Literal["extract", "transform"]:
    """A second extraction pass before moving on: the loop the canvas draws backwards."""
    return "transform" if cast("int", state.context.attempts) >= ATTEMPTS else "extract"
