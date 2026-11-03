"""api.docs: the OpenAPI pages as settings declare them — the canonical root, the aliases leading there, the renderers.

`DocsSettings` (DOCS_*) owns the vocabulary; this module only translates it into litestar at the edge, as
`middlewares.cors_config` does for CORS. The first renderer is served at the docs root itself, every
renderer also at its own subpath (`/docs/redoc`, ...), the raw spec at `<root>/openapi.json`. Each alias
answers 307 to the same subpath under the root — `/schema/openapi.json` lands on `/docs/openapi.json` —
and stays out of the spec. Settings are read at call time: `create_app` calls these once per worker."""

from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Final

from litestar import Request, get
from litestar.handlers import HTTPRouteHandler
from litestar.openapi.config import OpenAPIConfig
from litestar.openapi.plugins import (
    OpenAPIRenderPlugin,
    RapidocRenderPlugin,
    RedocRenderPlugin,
    ScalarRenderPlugin,
    StoplightRenderPlugin,
    SwaggerRenderPlugin,
)
from litestar.openapi.spec import Components
from litestar.response import Redirect
from litestar.status_codes import HTTP_307_TEMPORARY_REDIRECT

from infra.config.docs import DocsRenderer, DocsSettings
from infra.settings import settings as st

### each concrete plugin defaults its own subpath (`/swagger`, `/redoc`, ...): the map holds zero-argument factories.
RENDERERS: Final[Mapping[DocsRenderer, Callable[[], OpenAPIRenderPlugin]]] = MappingProxyType(
    {
        DocsRenderer.SWAGGER: SwaggerRenderPlugin,
        DocsRenderer.REDOC: RedocRenderPlugin,
        DocsRenderer.ELEMENTS: StoplightRenderPlugin,
        DocsRenderer.RAPIDOC: RapidocRenderPlugin,
        DocsRenderer.SCALAR: ScalarRenderPlugin,
    }
)


def openapi_config(
    title: str, version: str, *, components: Components | None = None, settings: DocsSettings | None = None
) -> OpenAPIConfig:
    """The OpenAPI config the settings declare: root path and renderers, the first one at the root."""
    ### the default resolves inside the body: an `st.docs` default would freeze at import and defeat the lazy singleton.
    resolved = st.docs if settings is None else settings
    return OpenAPIConfig(
        title=title,
        version=version,
        path=resolved.path,
        render_plugins=[RENDERERS[renderer]() for renderer in resolved.renderers],
        components=Components() if components is None else components,
    )


def routes(settings: DocsSettings | None = None) -> tuple[HTTPRouteHandler, ...]:
    """One redirect handler per alias root: the alias itself and every subpath under it, out of the spec."""
    resolved = st.docs if settings is None else settings

    def redirect_from(prefix: str) -> HTTPRouteHandler:
        async def redirect(request: Request) -> Redirect:
            ### the subpath survives the hop: an alias is the same tree under another root.
            return Redirect(
                path=f"{resolved.path}{request.url.path.removeprefix(prefix)}",
                status_code=HTTP_307_TEMPORARY_REDIRECT,
            )

        return get([prefix, f"{prefix}/{{rest:path}}"], name=f"docs.alias:{prefix}", include_in_schema=False)(redirect)

    return tuple(redirect_from(alias) for alias in resolved.aliases)
