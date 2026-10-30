"""e-api entrypoint: assembly by explicit registration only — importing this module does nothing.

`create_app` is the composition root and the factory granian calls per worker. Routers and
websockets enter through `register` calls — the include_router shape; middleware, the lifespan
chain and CORS enter through the constructor, and the order of `lifespan=[...]` is the startup
order: infra first (every later concern may depend on the loaded singletons), then the providers,
the engines over their ports and the services, sealed last. Dependency chains are wired by each
endpoint, never here. Nothing loads at import; the infra singletons load on the first touch, which
the infra lifespan makes.
"""

from importlib.metadata import version
from typing import cast

from litestar import Litestar
from litestar.openapi.spec import Components
from litestar.router import Router
from litestar.types import Middleware

from e_api.api import docs
from e_api.api.lifespan import db, engines, providers, sealed, services
from e_api.api.lifespan.infra import lifespan as infra_lifespan
from e_api.api.middlewares import MIDDLEWARES, cors_config
from e_api.api.router import health, user
from e_api.api.security import BEARER_SCHEME, SecuritySchemeName
from e_api.api.state import AppState
from e_api.websockets import telemetry
from infra.state import State


def create_app() -> Litestar:
    """Composition root: granian calls this per worker. Nothing here builds — the lifespans write the system graph."""
    ##### APP #####
    app = Litestar(
        route_handlers=[],
        ### Litestar's own state class, typed: one entry, the infra graph the lifespans write and seal.
        state=AppState({"system": State()}),
        lifespan=[
            infra_lifespan,
            db.lifespan,
            providers.lifespan,
            engines.lifespan,
            services.lifespan,
            sealed.lifespan,
        ],
        ### the declared union of middlewares crosses into litestar's looser `Middleware` alias here;
        ### asgi_correlation_id types its scope narrower than the protocol — wiring is exact, upstream typing is not.
        middleware=cast("list[Middleware]", list(MIDDLEWARES)),
        cors_config=cors_config(),
        ### pyproject is the version source of truth: uv-dynamic-versioning stamps it, dev reads 0.0.0.
        ### where the docs live, their aliases and renderers: DOCS_* settings, translated by api.docs.
        openapi_config=docs.openapi_config(
            title="e-api",
            version=version("e-api"),
            components=Components(security_schemes={SecuritySchemeName.BEARER.value: BEARER_SCHEME}),
        ),
    )

    ##### ROUTERS #####
    app.register(Router(path="/", route_handlers=list(health.ROUTES)))
    app.register(Router(path="/", route_handlers=list(user.ROUTES)))
    app.register(Router(path="/", route_handlers=list(telemetry.ws_routes())))
    app.register(Router(path="/", route_handlers=list(docs.routes())))
    return app
