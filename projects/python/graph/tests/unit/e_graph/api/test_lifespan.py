"""tests/unit: the lifespan contract — infra loaded once, providers opened as typed ports, state sealed last."""

import inspect

import pytest
from litestar.testing import TestClient

from e_graph.api.lifespan import graphs, instrument, logic, providers, sealed, services
from e_graph.api.lifespan.infra import SharedState
from e_graph.api.lifespan.infra import lifespan as infra_lifespan
from e_graph.instrument.graph import InstrumentGraph
from e_graph.instrument.state import EnginesState, ProvidersState
from e_graph.main import create_app
from engines.health import HealthEngine
from infra.errors import StoreError
from infra.logger import logger
from infra.settings import settings as st
from ports.documents import DocumentPort
from ports.http import HttpPort
from ports.pages import PagesPort
from ports.provider import Provider
from ports.store import StorePort
from ports.telemetry import TelemetryPort
from processors.doc import DocProcessor


def test_lifespans_are_declared_not_built() -> None:
    assert all(
        callable(cm)
        for cm in (
            infra_lifespan,
            providers.lifespan,
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


def test_providers_section_is_typed_and_ported(client) -> None:
    held = client.app.state.system.infra.providers
    assert isinstance(held, ProvidersState)
    assert all(isinstance(provider, Provider) for provider in held.named.values())
    assert isinstance(held.store, StorePort)
    assert isinstance(held.redis, StorePort)
    assert isinstance(held.http, HttpPort)
    assert isinstance(held.docling, DocumentPort)
    assert isinstance(held.pages, PagesPort)
    assert isinstance(held.telemetry, TelemetryPort)
    ### the instrument's tracer is handed the very driver the exit stack owns — one provider, one lifecycle.
    assert client.app.state.system.instrument.telemetry.provider is held.telemetry
    assert {role: provider.spec.name for role, provider in held.named.items()} == {
        "store": "sqlite",
        "telemetry": "otel",
        "redis": "redis",
        "http": "http",
        "docling": "docling-serve",
        "pages": "liteparse",
    }


def test_engines_section_holds_the_health_engine(client) -> None:
    engines = client.app.state.system.infra.engines
    assert isinstance(engines, EnginesState)
    assert isinstance(engines.health, HealthEngine)


def test_state_opens_sealed(client) -> None:
    state = client.app.state.system
    assert {"shared", "crypto", "infra", "instrument", "logic"} <= set(state)
    with pytest.raises(RuntimeError, match="Sealed"):
        state.held_by_the_lifespan_only = 1
    with pytest.raises(AttributeError, match="Sealed state has no node"):
        _ = state.typo_of_a_node


def test_graphs_section_holds_built_singletons(client) -> None:
    graphs = client.app.state.system.infra.graphs
    assert list(graphs) == ["doc", "filing", "note"]
    graph = graphs["doc"]
    assert isinstance(graph, InstrumentGraph)
    assert (graph.name, graph._compiled is not None) == ("doc", True)
    ### a singleton: every read of the section is the same built graph, never a rebuild.
    assert client.app.state.system.infra.graphs["doc"] is graph


async def test_providers_close_when_the_lifespan_exits() -> None:
    with TestClient(create_app()) as client:
        store = client.app.state.system.infra.providers.store
        assert client.get("/health").status_code == 200
        ### alive inside the cycle
        await store.get("anything")
    with pytest.raises(StoreError, match="not open"):
        ### the stack closed it on shutdown
        await store.get("anything")


def test_the_app_mounts_the_document_processor_over_the_docling_driver(client) -> None:
    infra = client.app.state.system.infra
    assert isinstance(infra.processors.doc, DocProcessor)
