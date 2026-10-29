"""pipelines.doc.nodes.validate.node: check the extraction, and route — back to extract for a retry, or forward."""

from typing import Any, Final, Literal, cast

import anyio

from e_graph.instrument.state import RunState
from e_graph.models.section import Section

ATTEMPTS: Final[int] = 2


async def node_validate(state: RunState) -> dict[str, Any]:
    """Check the extracted amount is a number."""
    await anyio.sleep(cast("float", state.context.get("pace", 0.0)))
    return await state.logic.orchestrator.node(Section.VALIDATE, state)


def route_validate(state: RunState) -> Literal["extract", "transform"]:
    """A second extraction pass before moving on: the loop the canvas draws backwards."""
    return "transform" if state.context.extract["EXT-amount"]["attempt"] >= ATTEMPTS else "extract"
