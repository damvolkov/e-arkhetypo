"""runners.owned.doc.classify.kind: the document's type, and with it the schema and rules downstream."""

from typing import Annotated, Any

import msgspec

from core.struct import CheckedStruct
from e_graph.instrument.state import RunState
from e_graph.logic.models import Call


class Args(CheckedStruct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """`kinds`: the types told apart, each by the word that marks it; anything else is `unknown`."""

    kinds: Annotated[tuple[str, ...], msgspec.Meta(min_length=1)] = ("invoice",)


async def run(state: RunState, call: Call) -> dict[str, Any]:
    """The first kind whose word the ingested text holds, or `unknown`."""
    text = state.context.ingest["ING-document"]["text"].lower()
    return {"kind": next((kind for kind in call.args.kinds if kind in text), "unknown")}
