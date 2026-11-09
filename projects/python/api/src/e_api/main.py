"""e-api entrypoint: assembly by explicit registration only — importing this module builds nothing.

`create_app` is the composition root and the factory granian calls per worker. One Litestar app serves both doors:
the REST routes, and the MCP endpoint whose tools are routes too (`mcp/registry`), each reached in process by the MCP
engine (`infra/mcp`) and answering it alone. Both sit behind the same middleware stack — the caller resolved once, from
the key — and the same guard, at the access each route and tool declares. Routers and websockets enter through
`register` calls — the include_router shape; middleware, the lifespan chain and CORS enter through the constructor, and
the order of `lifespan=[...]` is the startup order: infra first (every later concern may depend on the loaded
singletons), then the providers, the engines over their ports and crypto, the MCP server, sealed last. Dependency
chains are wired by each endpoint, never here. The settings are read once, at import (`infra.settings`); this root
reads `st` and hands each door its values.
"""

from importlib.metadata import version
from typing import Final, cast

from litestar import Litestar
from litestar.openapi.spec import Components
from litestar.router import Router
from litestar.types import Middleware

from e_api.api import docs
from e_api.api.lifespan import crypto, db, engines, mcp, providers, sealed
from e_api.api.lifespan.infra import lifespan as infra_lifespan
from e_api.api.middlewares import MIDDLEWARES, cors_config
from e_api.api.router import auth, health, user
from e_api.api.security import BEARER_SCHEME, SecuritySchemeName
from e_api.api.state import AppState
from e_api.infra.auth.guard import OPT, guard
from e_api.infra.auth.models import Access
from e_api.infra.logger import ELogger
from e_api.infra.mcp.guard import internal
from e_api.infra.settings import settings as st
from e_api.infra.state import State
from e_api.mcp import mount
from e_api.mcp import registry as tools
from e_api.websockets import telemetry

### the API's routers, each route declaring its access (`opt=OPT[...]`).
GUARDED: Final = (health.ROUTES, user.ROUTES, auth.ROUTES)


def create_app() -> Litestar:
    """Composition root: granian calls this per worker. Nothing here builds — the lifespans write the system graph."""
    ### the logger takes APP_ENV from the root, before any line is logged: JSON in prod, flat text elsewhere.
    ELogger.setup(env=st.APP_ENV)
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
            crypto.lifespan,
            mcp.lifespan,
            sealed.lifespan,
        ],
        ### the declared union of middlewares crosses into litestar's looser `Middleware` alias here;
        ### asgi_correlation_id types its scope narrower than the protocol — wiring is exact, upstream typing is not.
        middleware=cast("list[Middleware]", list(MIDDLEWARES)),
        cors_config=cors_config(origins=st.ALLOW_ORIGINS, methods=st.ALLOW_METHODS),
        ### pyproject is the version source of truth: uv-dynamic-versioning stamps it, dev reads 0.0.0.
        ### where the docs live, their aliases and renderers: DOCS_* settings, translated by api.docs.
        openapi_config=docs.openapi_config(
            title="e-api",
            version=version("e-api"),
            path=st.DOCS_PATH,
            renderers=st.DOCS_RENDERERS,
            components=Components(security_schemes={SecuritySchemeName.BEARER.value: BEARER_SCHEME}),
        ),
    )

    ##### ROUTERS #####
    ### every route passes the one guard, at the access it declares: each API route its own, the docs public (never
    ### authenticated).
    _ = [app.register(Router(path="/", route_handlers=list(routes), guards=[guard])) for routes in GUARDED]
    app.register(
        Router(path="/", route_handlers=list(telemetry.ws_routes()), opt=OPT[Access.ANONYMOUS], guards=[guard])
    )
    app.register(
        Router(
            path="/",
            route_handlers=list(docs.routes(path=st.DOCS_PATH, aliases=st.DOCS_ALIASES)),
            opt=OPT[Access.PUBLIC],
            guards=[guard],
        )
    )
    ### the MCP door: the tools, routes the engine alone may reach, each at the access its tool declares; the endpoint, any
    ### caller's — the token middleware has resolved who, each tool admits it at its own.
    app.register(Router(path="/", route_handlers=list(tools.ROUTES), guards=[internal, guard]))
    app.register(
        Router(path="/", route_handlers=list(mount.routes(path=st.MCP_PATH)), opt=OPT[Access.ANONYMOUS], guards=[guard])
    )
    return app
