"""runners.owned.doc.ingest.document: the document received, fingerprinted."""

import hashlib
from typing import Annotated, Any, Final, cast

import msgspec

from core.struct import CheckedStruct
from e_graph.instrument.state import RunState
from e_graph.logic.models import Call

SAMPLE: Final[str] = "invoice 42 · total 1250.00 EUR"


class Args(CheckedStruct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """`digest`: the fingerprint's size in bytes."""

    digest: Annotated[int, msgspec.Meta(ge=4, le=64)] = 8


async def run(state: RunState, call: Call) -> dict[str, Any]:
    """The document the run was seeded with (a sample invoice without one), and its blake2b fingerprint."""
    text = cast("str", state.context.get("document", SAMPLE))
    return {"text": text, "digest": hashlib.blake2b(text.encode(), digest_size=call.args.digest).hexdigest()}
