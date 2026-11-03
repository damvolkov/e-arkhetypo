"""infra/auth/guard: the one check between a request and its route, at both doors — the API's routes and the MCP's tools.

Who is asking is the token middleware's (`infra/auth/middleware`): a bad key never gets this far. Each entry declares
its access in its options (`opt=OPT[Access.USER]`), and `guard` — set on every router of both doors — admits the user
at it or raises the refusal it earns (401 for nobody, 403 for an account short of it), the same message whichever door.
A public entry is kept out of the middleware too: nothing is resolved for it. Litestar's own OPTIONS answer declares no
access and says only which methods a path takes: anyone's. Any other entry without an access fails loud, never open."""

from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from litestar.enums import HttpMethod

from e_infra.infra.auth.middleware import EXCLUDED, REFUSALS
from e_infra.infra.auth.models import Access, Caller
from e_infra.infra.auth.policy import AuthPolicy
from e_infra.infra.errors import RefusedError
from e_infra.infra.logger import logger

if TYPE_CHECKING:
    from collections.abc import Mapping

    from litestar.connection import ASGIConnection
    from litestar.handlers import BaseRouteHandler

### the option an entry's access is declared under, and each level's options, as an entry spells them: `opt=OPT[...]`;
### a public entry's options keep it out of authentication as well.
ACCESS: Final[str] = "access"
OPT: Final[Mapping[Access, Mapping[str, Access | bool]]] = MappingProxyType(
    {level: MappingProxyType({ACCESS: level, EXCLUDED: level is Access.PUBLIC}) for level in Access}
)


async def guard(connection: ASGIConnection[Any, Caller, Any, Any], handler: BaseRouteHandler) -> None:
    """The entry's declared access, met by the user the middleware resolved — or the refusal it earns."""
    declared = handler.opt.get(ACCESS)
    match (connection.scope.get("method"), declared):
        case (HttpMethod.OPTIONS, _) | (_, Access.PUBLIC):
            return
        case _:
            try:
                AuthPolicy.admit(connection.user, Access(declared))
            except RefusedError as exc:
                logger.warning("auth guard refused", path=connection.url.path, access=str(declared), reason=exc.message)
                raise REFUSALS[type(exc)](detail=exc.message) from exc
