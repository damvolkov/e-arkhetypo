"""tests/unit: the lifespan contract — core loaded once, edges opened as typed ports, graph sealed last."""

import inspect
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest
from litestar.testing import TestClient

from adapters.ports import HttpPort, StorePort
from core.logger import logger
from core.settings import Settings
from core.settings import settings as st
from core.state import State
from e_api.api.deps import registered_providers
from e_api.api.lifespan import adapters, sealed, services
from e_api.api.lifespan.adapters import AdaptersState
from e_api.api.lifespan.core import CoreState
from e_api.api.lifespan.core import lifespan as core_lifespan
from e_api.api.state import AppState
from e_api.main import create_app

if TYPE_CHECKING:
    from litestar import Litestar


def test_lifespans_are_declared_not_built() -> None:
    assert all(callable(cm) for cm in (core_lifespan, adapters.lifespan, services.lifespan, sealed.lifespan))
    assert list(inspect.signature(create_app).parameters) == []


def test_core_section_holds_the_loaded_singletons(client) -> None:
    core = client.app.state.system.core
    assert isinstance(core, CoreState)
    assert core.settings is st
    assert core.logger is logger


def test_singleton_load_is_idempotent(client) -> None:
    """Two touches, one instance: the LazyProxy cache pins the build for the whole process."""
    ### the graph section is the same object a global import reaches, and a second touch reuses the one build.
    assert client.app.state.system.core.settings.app is st.app
    assert st.app is st.app


def test_adapters_section_is_typed_and_ported(client) -> None:
    edges = client.app.state.system.adapters
    assert isinstance(edges, AdaptersState)
    assert isinstance(edges.store, StorePort)
    assert isinstance(edges.redis, StorePort)
    assert isinstance(edges.http, HttpPort)
    assert edges.store.name == "sqlite"
    assert edges.redis.name == "redis"
    assert edges.http.name == "http"


def test_graph_opens_sealed(client) -> None:
    graph = client.app.state.system
    assert {"core", "adapters", "crypto", "oauth"} <= set(graph)
    with pytest.raises(RuntimeError, match="Sealed"):
        graph.held_by_the_lifespan_only = 1
    with pytest.raises(AttributeError, match="Sealed state has no node"):
        _ = graph.typo_of_a_node


async def test_adapters_close_when_the_lifespan_exits() -> None:
    with TestClient(create_app()) as client:
        store = client.app.state.system.adapters.store
        assert client.get("/health").status_code == 200
        ### alive inside the cycle
        await store.get("anything")
    with pytest.raises(RuntimeError, match="not connected"):
        ### the stack closed it on shutdown
        await store.get("anything")


async def test_services_register_configured_idp(monkeypatch: pytest.MonkeyPatch) -> None:
    """The non-empty branch of the match: a metadata url means a named client in the registry."""
    monkeypatch.setattr(
        services,
        "st",
        Settings.load(
            oauth={"client_id": "cid", "client_secret": "sec", "server_metadata_url": "https://idp.test/openid"}
        ),
    )
    app = SimpleNamespace(state=AppState({"system": State()}))
    async with services.lifespan(cast("Litestar", app)):
        assert app.state.system.crypto is not None
    assert registered_providers(app.state.system.oauth) == ["dev"]
