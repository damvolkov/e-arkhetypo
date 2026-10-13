"""tests/unit: nodes.classify.node — invoice or unknown, said in the summary."""

from typing import TYPE_CHECKING

import pytest

from e_graph.nodes.classify.node import node_classify

if TYPE_CHECKING:
    from e_graph.instrument.state import RunState


@pytest.mark.parametrize(("document", "kind"), [("INVOICE 9", "invoice"), ("receipt 9", "unknown")])
async def test_classify_decides_the_kind(run_state: RunState, document: str, kind: str) -> None:
    run_state.context.document = document
    assert await node_classify(run_state) == f"classified as {kind}"
    assert run_state.context.kind == kind
