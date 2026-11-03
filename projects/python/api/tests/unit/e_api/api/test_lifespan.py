"""tests/unit: the lifespan contract — infra loaded once, providers opened as typed ports, engines over them, graph
sealed last."""

import inspect
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest
from litestar.testing import TestClient

from e_api.api.lifespan import engines, providers, sealed, services
from e_api.api.lifespan.engines import EnginesState
from e_api.api.lifespan.infra import SharedState
from e_api.api.lifespan.infra import lifespan as infra_lifespan
from e_api.api.lifespan.providers import ProvidersState
from e_api.api.state import AppState
from e_api.main import create_app
from engines.auth import AuthEngine
from infra.errors import StoreError
from infra.logger import logger
from infra.settings import settings as st
from infra.state import State
from ports.auth import AuthPort
from ports.database import DatabasePort
from ports.http import HttpPort
from ports.store import StorePort

if TYPE_CHECKING:
    from litestar import Litestar


def test_lifespans_are_declared_not_built() -> None:
    assert all(
        callable(cm)
        for cm in (infra_lifespan, providers.lifespan, engines.lifespan, services.lifespan, sealed.lifespan)
    )
    assert list(inspect.signature(create_app).parameters) == []


def test_shared_section_holds_the_loaded_singletons(client) -> None:
    shared = client.app.state.system.shared
    assert isinstance(shared, SharedState)
    assert shared.settings is st
    assert shared.logger is logger


def test_singleton_load_is_idempotent(client) -> None:
    """Two touches, one instance: the LazyProxy cache pins the build for the whole process."""
    ### the graph section is the same object a global import reaches, and a second touch reuses the one build.
    assert client.app.state.system.shared.settings.app is st.app
    assert st.app is st.app


def test_providers_section_is_typed_and_ported(client) -> None:
    section = client.app.state.system.providers
    assert isinstance(section, ProvidersState)
    assert isinstance(section.store, StorePort)
    assert isinstance(section.redis, StorePort)
    assert isinstance(section.http, HttpPort)
    assert isinstance(section.database, DatabasePort)
    assert isinstance(section.auth, AuthPort)
    assert section.store.spec.name == "sqlite"
    assert section.redis.spec.name == "redis"
    assert section.http.spec.name == "wreq"
    assert section.database.spec.name == "psqlpy"


def test_engines_section_is_typed(client) -> None:
    section = client.app.state.system.engines
    assert isinstance(section, EnginesState)
    assert isinstance(section.auth, AuthEngine)


def test_graph_opens_sealed(client) -> None:
    graph = client.app.state.system
    assert {"shared", "providers", "engines", "crypto"} <= set(graph)
    with pytest.raises(RuntimeError, match="Sealed"):
        graph.held_by_the_lifespan_only = 1
    with pytest.raises(AttributeError, match="Sealed state has no node"):
        _ = graph.typo_of_a_node


async def test_providers_close_when_the_lifespan_exits() -> None:
    with TestClient(create_app()) as client:
        store = client.app.state.system.providers.store
        assert client.get("/health").status_code == 200
        ### alive inside the cycle
        await store.get("anything")
    with pytest.raises(StoreError, match="not open"):
        ### the stack closed it on shutdown
        await store.get("anything")


async def test_services_write_crypto_to_the_graph() -> None:
    """Crypto is the one engine the services concern writes; it owns no resource to close."""
    app = SimpleNamespace(state=AppState({"system": State()}))
    async with services.lifespan(cast("Litestar", app)):
        assert app.state.system.crypto is not None
