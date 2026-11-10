"""infra/auth/middleware: who is asking, resolved once per request before any route runs — the auth package's only door.

`TokenMiddleware` is Litestar's authentication middleware over a `CallerResolver`: the request's `Authorization` header
becomes its user (`scope["user"]`, a `Caller`), read by every guard and by the MCP door through the same scope. The
resolver is built by a lifespan after the middleware stack exists, so the composition root hands in `locate`, how to
find it on the running app — read on each request, never held. No bearer is nobody, read without a lookup; a key
nobody holds, revoked or expired is a 401 before any route, at both doors. A route that opts out (`EXCLUDED`) is
never resolved. The token never sits in the scope: `auth` stays empty. `REFUSALS` is every auth error as its HTTP
answer, the one table the doors raise from — a missing or bad key challenged as RFC 6750 asks."""

from functools import partial
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from litestar.exceptions import HTTPException, NotAuthorizedException, PermissionDeniedException
from litestar.middleware import AbstractAuthenticationMiddleware, AuthenticationResult

from e_infra.infra.errors import AnonymousError, AuthError, ForbiddenError, UnknownTokenError
from e_infra.infra.logger import logger

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from litestar import Litestar
    from litestar.connection import ASGIConnection
    from litestar.datastructures import State
    from litestar.handlers import BaseRouteHandler
    from litestar.types import ASGIApp

    from e_infra.infra.auth.models import Caller
    from e_infra.infra.auth.resolver import CallerResolver

### the route option that keeps a route out of authentication: Litestar's own default key.
EXCLUDED: Final[str] = "exclude_from_auth"
CHALLENGE: Final[str] = "WWW-Authenticate"

### a request at either door once the middleware ran: the route's handler, the resolved caller, no auth, the app's state.
type Connection = ASGIConnection[BaseRouteHandler, Caller, None, State]

REFUSALS: Final[Mapping[type[AuthError], Callable[..., HTTPException]]] = MappingProxyType({
    UnknownTokenError: partial(NotAuthorizedException, headers={CHALLENGE: 'Bearer error="invalid_token"'}),
    AnonymousError: partial(NotAuthorizedException, headers={CHALLENGE: "Bearer"}),
    ForbiddenError: PermissionDeniedException,
})  # fmt: skip


class TokenMiddleware(AbstractAuthenticationMiddleware):
    """The bearer of every request as its caller, through the resolver `locate` finds; a bad key refused here."""

    def __init__(self, app: ASGIApp, *, locate: Callable[[Litestar], CallerResolver]) -> None:
        super().__init__(app)
        self._locate = locate

    async def authenticate_request(self, connection: Connection) -> AuthenticationResult:
        resolver = self._locate(connection.app)
        try:
            caller = await resolver.resolve(connection.headers.get("authorization", ""))
        except UnknownTokenError as exc:
            logger.warning("auth key refused", path=connection.url.path, reason=exc.message)
            raise REFUSALS[UnknownTokenError](detail=exc.message) from exc
        logger.debug("auth caller resolved", role=caller.role.value, name=caller.name)
        return AuthenticationResult(user=caller, auth=None)
