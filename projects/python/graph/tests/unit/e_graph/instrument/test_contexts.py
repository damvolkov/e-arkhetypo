"""tests/unit: instrument.contexts — the store of live runs' contexts."""

from e_graph.instrument.contexts import InstrumentContexts


def test_contexts_store_maps_live_runs() -> None:
    contexts = InstrumentContexts()
    opened = contexts.open("r1")
    assert (list(contexts), len(contexts), contexts["r1"]) == (["r1"], 1, opened)
    contexts.drop("r1")
    assert len(contexts) == 0
