"""runners.agnostic.document.read: the document at a context address, read page by page — the hybrid ingest.

The run names a path under a context key (default `source`); the document processor reads every page
with liteparse and sends the pages whose signals ask for it to docling. The output is the shared shape
every page-reading tool plugs into: `{"name", "pages": [{"number", "markdown"}], "deep"}`."""

from pathlib import Path
from typing import Annotated, Any

import msgspec

from core.struct import CheckedStruct
from e_graph.instrument.state import RunState
from e_graph.logic.models import Call


class Args(CheckedStruct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """`key`: the context entry naming the path of the document to read."""

    key: Annotated[str, msgspec.Meta(pattern=r"[a-z][a-z0-9_]*")] = "source"


async def run(state: RunState, call: Call) -> dict[str, Any]:
    """The document at the run's context key: its name, every page's markdown, the pages docling read."""
    match state.context.get(call.args.key):
        case str() as given if given:
            source = Path(given)
        case missing:
            msg = f"the run needs `{call.args.key}`, the path of the document to read; it was given {missing!r}"
            raise ValueError(msg)
    document = await state.infra.processors.doc.process(source, name=source.name)
    return {
        "name": document.name,
        "pages": [{"number": page.number, "markdown": page.markdown} for page in document.pages],
        "deep": list(document.deep),
    }
