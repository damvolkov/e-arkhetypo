"""runners.owned.doc.transform.record: the extraction mapped into the output record."""

from decimal import Decimal
from typing import Any

from e_graph.instrument.state import RunState
from e_graph.logic.models import Call


async def run(state: RunState, call: Call) -> dict[str, Any]:
    """Kind, fingerprint and amount in one record; an amount that is no number fails here."""
    context = state.context
    return {
        "kind": context.classify["CLS-kind"]["kind"],
        "digest": context.ingest["ING-document"]["digest"],
        "amount": str(Decimal(context.extract["EXT-amount"]["amount"])),
    }
