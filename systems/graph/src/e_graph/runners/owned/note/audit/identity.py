"""runners.owned.note.audit.identity: the ISIN is its own CUSIP wrapped in the issuing country — US, the nine characters, and the Luhn that closes them."""

from typing import Any

from e_graph.instrument.state import RunState
from e_graph.logic.models import Call
from e_graph.runners.agnostic.standard.checksum import Args as Checksum


async def run(state: RunState, call: Call) -> dict[str, Any]:
    """The ISIN the CUSIP implies, and whether the printed one is exactly that."""
    identifiers = state.context.extract["EXT-identifiers"]
    body = f"US{identifiers['cusip']}"
    expected = f"{body}{Checksum.luhn_digit(Checksum.expand(body))}"
    return {"expected": expected, "holds": expected == identifiers["isin"]}
