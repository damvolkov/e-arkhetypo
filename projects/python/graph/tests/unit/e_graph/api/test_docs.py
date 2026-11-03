"""tests/unit: api.docs — the OpenAPI pages where DOCS_* says, every alias landing on the same subpath."""

import pytest
from litestar import Litestar
from litestar.openapi.plugins import RedocRenderPlugin, ScalarRenderPlugin, SwaggerRenderPlugin
from litestar.openapi.spec import Components
from litestar.status_codes import HTTP_307_TEMPORARY_REDIRECT
from litestar.testing import TestClient

from e_graph.api.docs import RENDERERS, openapi_config, routes
from infra.config.docs import DocsRenderer, DocsSettings


@pytest.mark.parametrize("path", ["/docs", "/docs/swagger", "/docs/redoc", "/docs/elements", "/docs/rapidoc"])
def test_default_renderers_served_under_docs(client, path: str) -> None:
    assert client.get(path).status_code == 200


def test_docs_root_is_swagger_and_spec_is_beside_it(client) -> None:
    assert "SwaggerUIBundle" in client.get("/docs").text
    assert client.get("/docs/openapi.json").json()["info"]["title"] == "e-graph"


@pytest.mark.parametrize(
    ("alias", "target"),
    [("/schema", "/docs"), ("/schema/redoc", "/docs/redoc"), ("/schema/openapi.json", "/docs/openapi.json")],
)
def test_schema_aliases_docs_keeping_the_subpath(client, alias: str, target: str) -> None:
    response = client.get(alias, follow_redirects=False)
    assert (response.status_code, response.headers["location"]) == (HTTP_307_TEMPORARY_REDIRECT, target)
    assert client.get(alias).status_code == 200


def test_aliases_stay_out_of_the_spec(client) -> None:
    assert not [path for path in client.get("/docs/openapi.json").json()["paths"] if path.startswith("/schema")]


def test_every_renderer_has_a_plugin() -> None:
    assert set(RENDERERS) == set(DocsRenderer)


def test_settings_decide_root_renderers_and_aliases() -> None:
    settings = DocsSettings(path="/api/docs", aliases=["/a", "/b"], renderers=["scalar", "redoc"])
    config = openapi_config("t", "1", settings=settings)
    assert config.path == "/api/docs"
    assert [type(plugin) for plugin in config.render_plugins] == [ScalarRenderPlugin, RedocRenderPlugin]
    with TestClient(Litestar(list(routes(settings)), openapi_config=config)) as client:
        assert client.get("/b/redoc", follow_redirects=False).headers["location"] == "/api/docs/redoc"
        assert client.get("/a").status_code == 200


def test_components_pass_through() -> None:
    components = Components(security_schemes={})
    config = openapi_config("t", "1", components=components, settings=DocsSettings(renderers=["swagger"]))
    assert config.components is components
    assert [type(plugin) for plugin in config.render_plugins] == [SwaggerRenderPlugin]


def test_no_aliases_no_routes() -> None:
    assert routes(DocsSettings(aliases=[])) == ()
