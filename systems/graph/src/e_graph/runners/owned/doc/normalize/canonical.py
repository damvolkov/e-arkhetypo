"""runners.owned.doc.normalize.canonical: the document folded into its canonical form."""

from typing import Any

from e_graph.instrument.state import RunState
from e_graph.logic.models import Call


async def run(state: RunState, call: Call) -> dict[str, Any]:
    """The ingested text, lowercased, its whitespace collapsed."""
    return {"text": " ".join(state.context.ingest["ING-document"]["text"].lower().split())}
