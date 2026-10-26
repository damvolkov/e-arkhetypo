"""api.security: bearer enforcement and the OpenAPI contract — `ops/crypto` is the only source of truth.

The guard verifies the token and parks its claims in the connection scope; `provide_current_user`
(api.deps) turns those claims into a `User`. Guards run before dependencies, so a handler that
depends on `current_user` is automatically behind the bearer check once `auth_guard` is attached.
"""

from enum import StrEnum
from typing import TYPE_CHECKING, Any, Final

from litestar.exceptions import NotAuthorizedException
from litestar.openapi.spec import SecurityScheme

from e_api.api.state import AppState
from ops.crypto import TokenError

if TYPE_CHECKING:
    from litestar.connection import ASGIConnection
    from litestar.handlers import BaseRouteHandler


##### CONTRACT #####
class SecuritySchemeName(StrEnum):
    BEARER = "bearerAuth"


BEARER_SCHEME = SecurityScheme(type="http", scheme="bearer", bearer_format="JWT")
### OpenAPI requirement maps key by scheme id: the enum owns the vocabulary, `.value` is the str edge litestar types.
SECURITY: Final[list[dict[str, list[str]]]] = [{SecuritySchemeName.BEARER.value: []}]


##### HELPERS #####
def bearer_claims(request: ASGIConnection) -> dict[str, Any]:
    """Verified claims for the request's bearer token, or 401."""
    match request.headers.get("authorization", "").split():
        case ["Bearer", token]:
            try:
                return AppState.of(request.app).system.crypto.verify_token(token)
            except TokenError as exc:
                raise NotAuthorizedException(detail=str(exc)) from exc
        case _:
            raise NotAuthorizedException(detail="Bearer token required")


async def auth_guard(connection: ASGIConnection, _handler: BaseRouteHandler) -> None:
    """Litestar calls guards with (connection, handler): this one authenticates and nothing else.

    Claims are not smuggled through the scope — `provide_current_user` re-derives them (a verify is
    microseconds, an implicit side channel between guard and dependency is forever).
    """
    bearer_claims(connection)
