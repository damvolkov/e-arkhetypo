"""tests/unit: the lifespan contract — infra loaded once, edges opened as typed ports, state sealed last."""

import inspect

import pytest
from litestar.testing import TestClient

from adapters.ports import DocumentPort, HttpPort, StorePort, TelemetryPort
from e_graph.api.lifespan import adapters, graphs, instrument, logic, sealed, services
from e_graph.api.lifespan.infra import SharedState
from e_graph.api.lifespan.infra import lifespan as infra_lifespan
from e_graph.instrument.graph import InstrumentGraph
from e_graph.instrument.state import AdaptersState
from e_graph.main import create_app
from infra.logger import logger
from infra.settings import settings as st
from processors.doc import DocProcessor


def test_lifespans_are_declared_not_built() -> None:
    assert all(
        callable(cm)
        for cm in (
            infra_lifespan,
            adapters.lifespan,
            services.lifespan,
            instrument.lifespan,
            logic.lifespan,
            graphs.lifespan,
            sealed.lifespan,
        )
    )
    assert list(inspect.signature(create_app).parameters) == []


def test_shared_section_holds_the_loaded_singletons(client) -> None:
    shared = client.app.state.system.shared
    assert isinstance(shared, SharedState)
    assert shared.settings is st
    assert shared.logger is logger


def test_singleton_load_is_idempotent(client) -> None:
    """Two touches, one instance: the LazyProxy cache pins the build for the whole process."""
    ### the state section is the same object a global import reaches, and a second touch reuses the one build.
    assert client.app.state.system.shared.settings.app is st.app
    assert st.app is st.app


def test_adapters_section_is_typed_and_ported(client) -> None:
    edges = client.app.state.system.adapters
    assert isinstance(edges, AdaptersState)
    assert isinstance(edges.store, StorePort)
    assert isinstance(edges.redis, StorePort)
    assert isinstance(edges.http, HttpPort)
    assert isinstance(edges.docling, DocumentPort)
    assert isinstance(edges.telemetry, TelemetryPort)
    assert edges.telemetry.name == "otel"
    ### the instrument's tracer is handed the very adapter the exit stack owns — one provider, one lifecycle.
    assert client.app.state.system.instrument.telemetry.provider is edges.telemetry
    assert edges.store.name == "sqlite"
    assert edges.redis.name == "redis"
    assert edges.http.name == "http"
    assert edges.docling.name == "docling"


def test_state_opens_sealed(client) -> None:
    state = client.app.state.system
    assert {"shared", "adapters", "crypto", "instrument", "logic", "graphs"} <= set(state)
    with pytest.raises(RuntimeError, match="Sealed"):
        state.held_by_the_lifespan_only = 1
    with pytest.raises(AttributeError, match="Sealed state has no node"):
        _ = state.typo_of_a_node


def test_graphs_section_holds_built_singletons(client) -> None:
    graphs = client.app.state.system.graphs
    assert list(graphs) == ["doc", "filing", "note"]
    graph = graphs["doc"]
    assert isinstance(graph, InstrumentGraph)
    assert (graph.name, graph._compiled is not None) == ("doc", True)
    ### a singleton: every read of the section is the same built graph, never a rebuild.
    assert client.app.state.system.graphs["doc"] is graph


async def test_adapters_close_when_the_lifespan_exits() -> None:
    with TestClient(create_app()) as client:
        store = client.app.state.system.adapters.store
        assert client.get("/health").status_code == 200
        ### alive inside the cycle
        await store.get("anything")
    with pytest.raises(RuntimeError, match="not connected"):
        ### the stack closed it on shutdown
        await store.get("anything")


def test_the_app_mounts_the_document_processor_over_the_docling_edge(client) -> None:
    infra = client.app.state.system.infra
    assert isinstance(infra.processors.doc, DocProcessor)
