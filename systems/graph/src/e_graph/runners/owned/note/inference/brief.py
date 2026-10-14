"""runners.owned.note.inference.brief: the material the plain-language summary reads — terms, payoff and scenarios."""

from typing import Any

import msgspec

from e_graph.instrument.state import RunState
from e_graph.logic.models import Call


async def pre_run(state: RunState, call: Call) -> str:
    """The term sheet, the payoff as printed, and the scenario table — one JSON block for the summarizer."""
    extract = state.context.extract
    material: dict[str, Any] = {
        "terms": extract["EXT-terms"],
        "payoff": extract["EXT-payoff"],
        "scenarios": call.inputs["INF-scenarios"],
        "return": call.inputs.get("INF-max-return", {}),
    }
    return msgspec.json.format(msgspec.json.encode(material), indent=2).decode()
