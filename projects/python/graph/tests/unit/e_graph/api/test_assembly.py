"""tests/unit: the assembly itself — lazy factory, declarative registration, composite settings."""

from importlib.metadata import version

import e_graph.main as entrypoint
from infra.settings import Settings
from infra.settings import settings as st


def test_importing_main_has_no_side_effects() -> None:
    assert callable(entrypoint.create_app)
    assert not hasattr(entrypoint, "app"), "the factory must stay lazy: granian builds it per worker"


def test_composite_settings_expose_every_scope() -> None:
    scopes = set(Settings.model_fields)
    assert {"api", "app", "crypto", "engines", "processors", "providers", "ui"} <= scopes
    assert st.providers.drivers.store.redis.url.get_secret_value().startswith("redis://")
    assert st.app.port == 8000


def test_create_app_registers_every_router(client) -> None:
    paths = {route.path for route in client.app.routes}
    assert {
        "/health",
        "/api/ui",
        "/api/pipelines/list",
        "/api/pipelines/topology/{pipeline_id:str}",
        "/api/pipelines/batch/{pipeline_id:str}",
        "/api/pipelines/stream/{pipeline_id:str}",
        "/docs",
    } <= paths


def test_chains_wire_endpoints_not_the_app(client) -> None:
    ### every dependency link is declared by the route that consumes it
    assert client.app.dependencies == {}


def test_openapi_version_comes_from_the_distribution(client) -> None:
    assert client.app.openapi_config.version == version("e-graph")
