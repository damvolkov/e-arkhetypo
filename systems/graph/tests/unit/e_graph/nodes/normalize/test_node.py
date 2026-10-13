"""tests/unit: nodes.normalize.node — lowercase, single-spaced canonical text, no summary of its own."""

from typing import TYPE_CHECKING

from e_graph.nodes.normalize.node import node_normalize

if TYPE_CHECKING:
    from e_graph.instrument.state import RunState


async def test_normalize_folds_case_and_space(run_state: RunState) -> None:
    run_state.context.document = "  Invoice   42\n TOTAL 3 "
    assert await node_normalize(run_state) is None
    assert run_state.context.canonical == "invoice 42 total 3"
