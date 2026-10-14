"""runners.owned.note.audit.compare: the material the coherence call reads — the payoff's words beside the sheet's numbers."""

from typing import Any

import msgspec

from e_graph.instrument.state import RunState
from e_graph.logic.models import Call


async def pre_run(state: RunState, call: Call) -> str:
    """The note's payoff as the document words it and the term sheet as the section extracted it, one JSON block."""
    extract = state.context.extract
    material: dict[str, Any] = {"payoff_as_stated": extract["EXT-payoff"], "term_sheet": extract["EXT-terms"]}
    return msgspec.json.format(msgspec.json.encode(material), indent=2).decode()
