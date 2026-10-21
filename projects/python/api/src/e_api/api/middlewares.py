"""api.middlewares: the ASGI stack, declared once as data — correlation, CORS, and the house access log.

The config struct lives in the settings package (`core.settings.api`); this module only
translates it into litestar behaviour and owns the house middleware.
"""

import time
from typing import TYPE_CHECKING, Final

from asgi_correlation_id import CorrelationIdMiddleware
from litestar.config.cors import CORSConfig
from litestar.enums import HttpMethod as LitestarHttpMethod
from litestar.types import ASGIApp

from core.logger import logger
from core.settings import settings as st

if TYPE_CHECKING:
    from litestar.types import Message, Receive, Scope, Send

    from core.settings.api import ApiSettings


##### MIDDLEWARES #####
class AccessLogMiddleware:
    """House standard for pure-ASGI middleware: one structured line per request, correlation id included."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        match scope["type"]:
            case "http":
                started = time.perf_counter()
                status = 0

                async def send_and_watch(message: Message) -> None:
                    nonlocal status
                    status = message.get("status", status)
                    await send(message)

                await self._app(scope, receive, send_and_watch)
                logger.info(
                    "request",
                    method=scope["method"],
                    path=scope["path"],
                    status=status,
                    duration_ms=round((time.perf_counter() - started) * 1000, 2),
                )
            case _:
                await self._app(scope, receive, send)


def cors_config(settings: ApiSettings | None = None) -> CORSConfig:
    """Translate the settings struct into litestar's config object — data in, behaviour out."""
    ### the default resolves inside the body: an `st.api` default would freeze at import and defeat the lazy singleton.
    resolved = st.api if settings is None else settings
    ### two verb enums, one wire contract: settings own the vocabulary, values cross into litestar's at this edge.
    return CORSConfig(
        allow_origins=resolved.allow_origins,
        allow_methods=[LitestarHttpMethod(method.value) for method in resolved.allow_methods],
        allow_headers=["*"],
    )


type MiddlewareClass = type[CorrelationIdMiddleware] | type[AccessLogMiddleware]
### the honest union of the two classes this stack ships; litestar's own `Middleware` alias is looser,
### and asgi_correlation_id types its scope narrower than the protocol — the wiring edge is main.py.
MIDDLEWARES: Final[tuple[MiddlewareClass, ...]] = (CorrelationIdMiddleware, AccessLogMiddleware)
