"""tests/unit: the lifespan contract — infra loaded once, providers opened as typed ports, state sealed last."""

import inspect

import pytest
from litestar.testing import TestClient

from e_graph.api.lifespan import graphs, instrument, logic, providers, sealed, services
from e_graph.api.lifespan.infra import SharedState
from e_graph.api.lifespan.infra import lifespan as infra_lifespan
from e_graph.engines.health import HealthEngine
from e_graph.infra.errors import StoreError
from e_graph.infra.logger import logger
from e_graph.instrument.graph import InstrumentGraph
from e_graph.instrument.state import EnginesState, ProvidersState
from e_graph.main import create_app
from e_graph.ports.documents import DocumentPort
from e_graph.ports.http import HTTPPort
from e_graph.ports.markdown import MarkdownPort
from e_graph.ports.pages import PagesPort
from e_graph.ports.provider import Provider
from e_graph.ports.store import StorePort
from e_graph.ports.telemetry import TelemetryPort
from e_graph.processors.doc import DocProcessor


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


def test_shared_section_holds_the_logger_never_the_settings(client) -> None:
    shared = client.app.state.system.shared
    assert (isinstance(shared, SharedState), shared.logger is logger, hasattr(shared, "settings")) == (
        True,
        True,
        False,
    )


def test_providers_section_is_typed_and_ported(client) -> None:
    held = client.app.state.system.infra.providers
    assert isinstance(held, ProvidersState)
    assert all(isinstance(provider, Provider) for provider in held.named.values())
    assert isinstance(held.store, StorePort)
    assert isinstance(held.redis, StorePort)
    assert isinstance(held.http, HTTPPort)
    assert isinstance(held.docling, DocumentPort)
    assert isinstance(held.pages, PagesPort)
    assert isinstance(held.markdown, MarkdownPort)
    assert isinstance(held.telemetry, TelemetryPort)
    ### the instrument's tracer is handed the very driver the exit stack owns — one provider, one lifecycle.
    assert client.app.state.system.instrument.telemetry.provider is held.telemetry
    assert {role: provider.spec.name for role, provider in held.named.items()} == {
        "store": "sqlite",
        "telemetry": "otel",
        "redis": "redis",
        "http": "wreq",
        "docling": "docling-serve",
        "pages": "liteparse",
        "markdown": "anytomd",
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
