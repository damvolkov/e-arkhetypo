"""tests/unit: the assembly itself — lazy factory, declarative registration, composite settings."""

from importlib.metadata import version

import e_api.main as entrypoint
from infra.settings import Settings
from infra.settings import settings as st


def test_importing_main_has_no_side_effects() -> None:
    assert callable(entrypoint.create_app)
    assert not hasattr(entrypoint, "app"), "the factory must stay lazy: granian builds it per worker"


def test_composite_settings_expose_every_scope() -> None:
    scopes = set(Settings.model_fields)
    assert {"api", "app", "crypto", "db", "http", "oauth", "redis"} <= scopes
    assert st.redis.redis_url.startswith("redis://")
    assert st.app.app_port == 8000


def test_create_app_registers_every_router(client) -> None:
    paths = {route.path for route in client.app.routes}
    assert {
        "/health",
        "/oauth/providers",
        "/users",
        "/users/{user_id:uuid}",
        "/ws/telemetry",
        "/docs",
        "/schema",
    } <= paths


def test_chains_wire_endpoints_not_the_app(client) -> None:
    ### every dependency link is declared by the route that consumes it
    assert client.app.dependencies == {}


def test_openapi_contract_comes_from_its_owners(client) -> None:
    ### the distribution stamps the version; the bearer id is the SecuritySchemeName enum's value.
    config = client.app.openapi_config
    assert config.version == version("e-api")
    assert "bearerAuth" in config.components.security_schemes
