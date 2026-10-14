"""runners.owned.doc.validate.amount: whether the extracted amount is a number."""

from typing import Any

from e_graph.instrument.state import RunState
from e_graph.logic.models import Call


async def run(state: RunState, call: Call) -> dict[str, Any]:
    """The extracted amount read as a decimal number: valid, or not."""
    return {"valid": state.context.extract["EXT-amount"]["amount"].replace(".", "", 1).isdigit()}
