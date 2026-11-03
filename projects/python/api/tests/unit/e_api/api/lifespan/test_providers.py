"""tests/unit/e_api/api/lifespan/providers: every provider opened on one stack, in field order, by its role."""

from dataclasses import fields
from typing import Final

import pytest
from litestar.testing import TestClient

from e_api.api.lifespan.providers import ProvidersState
from e_api.main import create_app
from infra.errors import StoreError
from ports.auth import AuthPort
from ports.database import DatabasePort
from ports.http import HTTPPort
from ports.provider import Provider
from ports.store import StorePort

### the roles are the section's fields: a provider the export drops leaves this list with it.
ROLES: Final[tuple[str, ...]] = tuple(each.name for each in fields(ProvidersState))


async def test_providers_named_in_field_order(client: TestClient) -> None:
    """Each role maps to the provider it holds, every one satisfying the lifecycle contract."""
    roles = client.app.state.system.providers.named
    assert tuple(roles) == ROLES
    assert all(isinstance(provider, Provider) for provider in roles.values())


async def test_providers_open_inside_the_cycle(client: TestClient) -> None:
    """The open sqlite file answers its health while the app runs."""
    assert await client.app.state.system.providers.named["store"].health()


async def test_providers_section_is_typed_and_ported(client: TestClient) -> None:
    section = client.app.state.system.providers
    assert isinstance(section, ProvidersState)
    assert isinstance(section.store, StorePort)
    assert isinstance(section.redis, StorePort)
    assert isinstance(section.http, HTTPPort)
    assert isinstance(section.database, DatabasePort)
    assert isinstance(section.auth, AuthPort)
    assert section.store.spec.name == "sqlite"
    assert section.redis.spec.name == "redis"
    assert section.http.spec.name == "wreq"
    assert section.database.spec.name == "psqlpy"


async def test_providers_close_when_the_lifespan_exits() -> None:
    with TestClient(create_app()) as client:
        store = client.app.state.system.providers.store
        assert client.get("/health").status_code == 200
        ### alive inside the cycle
        await store.get("anything")
    with pytest.raises(StoreError, match="not open"):
        ### the stack closed it on shutdown
        await store.get("anything")
