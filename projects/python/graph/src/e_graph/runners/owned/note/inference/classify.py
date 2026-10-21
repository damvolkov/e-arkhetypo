"""runners.owned.note.inference.classify: the material a classifier reads — the term sheet and the payoff as printed."""

from typing import Any

import msgspec

from e_graph.instrument.state import RunState
from e_graph.logic.models import Call


async def pre_run(state: RunState, call: Call) -> str:
    """The extracted terms and the note's own payoff text, as one block of JSON the classifiers can weigh."""
    extract = state.context.extract
    material: dict[str, Any] = {
        "terms": extract["EXT-terms"],
        "payoff": extract["EXT-payoff"],
        "listing_and_risk": {"listed": extract["EXT-listing"]["listed"], "risks": extract["EXT-risks"]["risks"]},
        "amounts": {"aggregate_principal": extract["EXT-amounts"]["aggregate_principal"][0]},
    }
    return msgspec.json.format(msgspec.json.encode(material), indent=2).decode()
