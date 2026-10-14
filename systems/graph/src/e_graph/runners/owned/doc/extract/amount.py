"""runners.owned.doc.extract.amount: the amount after the word `total`, counting each extraction pass."""

import re
from typing import Any, Final

from e_graph.instrument.state import RunState
from e_graph.logic.models import Call

NUMBER: Final[re.Pattern[str]] = re.compile(r"\d+(?:\.\d+)?")


async def run(state: RunState, call: Call) -> dict[str, Any]:
    """The first number after `total` in the canonical text (empty when there is none), and the pass it was read in."""
    match state.context.get("fail", False):
        case True:
            msg = "extraction failed on purpose"
            raise RuntimeError(msg)
        case _:
            found = NUMBER.search(state.context.normalize["NOR-canonical"]["text"].split("total")[-1])
            attempt = state.context.extract.get(call.spec, {}).get("attempt", 0) + 1
            return {"amount": found.group() if found else "", "attempt": attempt}
