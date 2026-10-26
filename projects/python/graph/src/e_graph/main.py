"""e-graph entrypoint: assembly by explicit registration only — importing this module does nothing.

`create_app` is the composition root and the factory granian calls per worker. Routers enter
through `register` calls — the include_router shape; middleware, the lifespan
chain and CORS enter through the constructor, and the order of `lifespan=[...]` is the startup
order: infra first (every later concern may depend on the loaded singletons), then the edges, the
services and the built graphs, sealed last. Dependency chains are wired by each endpoint, never
here. Nothing loads at import; the infra singletons load on the first touch, which the infra lifespan
makes.
"""

from importlib.metadata import version
from typing import cast

from litestar import Litestar
from litestar.router import Router
from litestar.types import Middleware

from e_graph.api import docs
from e_graph.api.lifespan import adapters, db, sealed, services
from e_graph.api.lifespan.graphs import lifespan as graphs_lifespan
from e_graph.api.lifespan.infra import lifespan as infra_lifespan
from e_graph.api.middlewares import MIDDLEWARES, cors_config
from e_graph.api.router import health, pipelines, specs, ui
from e_graph.api.state import AppState
from infra.state import State


def create_app() -> Litestar:
    """Composition root: granian calls this per worker. Nothing here builds — the lifespans write the system graph."""
    ##### APP #####
    app = Litestar(
        route_handlers=[],
        ### Litestar's own state class, typed: one entry, the infra graph the lifespans write and seal.
        state=AppState({"system": State()}),
        lifespan=[infra_lifespan, db.lifespan, adapters.lifespan, services.lifespan, graphs_lifespan, sealed.lifespan],
        ### the declared union of middlewares crosses into litestar's looser `Middleware` alias here;
        ### asgi_correlation_id types its scope narrower than the protocol — wiring is exact, upstream typing is not.
        middleware=cast("list[Middleware]", list(MIDDLEWARES)),
        cors_config=cors_config(),
        ### pyproject is the version source of truth: uv-dynamic-versioning stamps it, dev reads 0.0.0.
        ### where the docs live, their aliases and renderers: DOCS_* settings, translated by api.docs.
        openapi_config=docs.openapi_config(title="e-graph", version=version("e-graph")),
    )

    ##### ROUTERS #####
    app.register(Router(path="/", route_handlers=list(health.ROUTES)))
    app.register(Router(path=pipelines.PREFIX, route_handlers=list(pipelines.ROUTES)))
    app.register(Router(path=specs.PREFIX, route_handlers=list(specs.ROUTES)))
    app.register(Router(path="/", route_handlers=list(ui.ROUTES)))
    app.register(Router(path="/", route_handlers=list(docs.routes())))
    app.register(ui.router())
    return app
