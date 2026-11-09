"""tests/unit/e_api/main: the composition root — a lazy factory, every router registered, the contract stamped."""

import inspect
from importlib.metadata import version
from typing import TYPE_CHECKING

import e_api.main as entrypoint
from e_api.main import create_app

if TYPE_CHECKING:
    from litestar.testing import TestClient


async def test_import_has_no_side_effects() -> None:
    assert callable(entrypoint.create_app)
    assert not hasattr(entrypoint, "app"), "the factory must stay lazy: granian builds it per worker"


async def test_create_app_takes_nothing() -> None:
    assert list(inspect.signature(create_app).parameters) == []


def test_create_app_lifespans_write_the_graph_in_startup_order(client: TestClient) -> None:
    """Infra first, then the providers, the engines over them, crypto, the MCP server; sealed last."""
    assert list(client.app.state.system) == ["shared", "providers", "engines", "crypto", "mcp"]


def test_create_app_registers_every_router(client: TestClient) -> None:
    paths = {route.path for route in client.app.routes}
    assert {
        "/health",
        "/ready",
        "/auth/me",
        "/auth/accounts",
        "/auth/accounts/{name:str}/token",
        "/users",
        "/users/{user_id:uuid}",
        "/ws/telemetry",
        "/docs",
        "/schema",
    } <= paths


def test_create_app_chains_wire_endpoints_not_the_app(client: TestClient) -> None:
    ### every dependency link is declared by the route that consumes it
    assert client.app.dependencies == {}


def test_create_app_openapi_contract_comes_from_its_owners(client: TestClient) -> None:
    ### the distribution stamps the version; the bearer id is the SecuritySchemeName enum's value.
    config = client.app.openapi_config
    assert config.version == version("e-api")
    assert "bearerAuth" in config.components.security_schemes
