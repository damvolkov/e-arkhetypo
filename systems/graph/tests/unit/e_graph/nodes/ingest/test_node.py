"""tests/unit: nodes.ingest.node — the default document, the fingerprint, the summary."""

from typing import TYPE_CHECKING

from e_graph.nodes.ingest.node import node_ingest

if TYPE_CHECKING:
    from e_graph.instrument.state import RunState


async def test_ingest_fingerprints_the_default_document(run_state: RunState) -> None:
    summary = await node_ingest(run_state)
    assert run_state.context.document.startswith("invoice 42")
    assert len(run_state.context.digest) == 16
    assert summary == f"registered {run_state.context.digest}"


async def test_ingest_keeps_a_seeded_document(run_state: RunState) -> None:
    run_state.context.document = "seeded"
    await node_ingest(run_state)
    assert run_state.context.document == "seeded"
