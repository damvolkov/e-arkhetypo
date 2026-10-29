"""tests/unit: api.deps — the wiring vocabulary and the links over the live system graph."""

import pytest
from litestar.exceptions import NotFoundException

from e_graph.api.deps import DepKey, correlation_id, graph, graphs, lab, section, store, system
from e_graph.api.state import AppState


def test_dep_key_values_are_the_link_parameter_names() -> None:
    """StrEnum auto() lowercases the member name: the enum and the injected signature cannot drift apart."""
    assert [key.value for key in DepKey] == ["system", "store", "graphs", "graph", "section", "lab", "correlation_id"]


def test_correlation_id_empty_outside_a_request() -> None:
    assert correlation_id() == ""


def test_links_chain_over_the_live_system(client) -> None:
    """The root reads Litestar's reserved state, rebuilt as AppState over the same dict, as Litestar injects it."""
    root = system(AppState(client.app.state))
    assert root is client.app.state.system
    assert store(root) is root.infra.adapters.store
    assert graphs(root) is root.infra.graphs
    assert graph("doc", root.infra.graphs) is root.infra.graphs["doc"]
    assert section("extract", root.infra.graphs["filing"]) == "extract"
    assert lab(root).sections is not None


def test_graph_link_refuses_an_unknown_name(client) -> None:
    with pytest.raises(NotFoundException, match="known: \\['doc', 'filing', 'note'\\]"):
        graph("nope", client.app.state.system.infra.graphs)


def test_section_link_refuses_what_the_pipeline_does_not_mount(client) -> None:
    with pytest.raises(NotFoundException, match="filing mounts no 'validate'; mounted: \\['audit', 'extract'"):
        section("validate", client.app.state.system.infra.graphs["filing"])
