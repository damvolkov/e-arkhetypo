"""api.router.auth: the accounts that may call — who the caller is, and the admin's keys and accounts.

`GET /auth/me` answers who the bearer names: an account's id, name and role, or nobody. Everything else is the admin's:
`GET /auth/accounts` lists the accounts; `POST /auth/accounts/{name}/token` makes the account of `name` when missing and
hands out one fresh key, every earlier one revoked — the key shown this once, kept only as its digest; the admin's own
name rotates the admin's key. `DELETE /auth/accounts/{name}/token` revokes every key of an account. The rules are the auth
engine's (`engines/auth`): a name is plain — lower case letters, digits, `-` and `_` — or a 400; an engine with no secret
makes no account (503). The admin's first key comes from `python -m e_api admin`, on the service's own host.
"""

from typing import Any, Final

import msgspec
from litestar import Request, Response, delete, get, post, put
from litestar.di import NamedDependency, Provide
from litestar.handlers import HTTPRouteHandler
from litestar.params import FromPath, JSONBody
from litestar.status_codes import HTTP_200_OK, HTTP_400_BAD_REQUEST, HTTP_503_SERVICE_UNAVAILABLE

from e_api.api.deps import DepKey, auth, caller, graph
from e_api.api.security import SECURITY
from e_api.engines.auth import AuthEngine
from e_api.infra.auth.guard import OPT
from e_api.infra.auth.models import Access, Account, Caller, Issued
from e_api.infra.errors import AuthClosedError, AuthNameError


##### CONTRACT #####
class Revoked(msgspec.Struct, frozen=True, kw_only=True):
    """How many keys of an account were revoked."""

    name: str
    revoked: int


##### HELPERS #####
def closed(_request: Request[Any, Any, Any], exc: AuthClosedError) -> Response[dict[str, str]]:
    """No secret: the engine makes no account."""
    return Response({"detail": exc.message}, status_code=HTTP_503_SERVICE_UNAVAILABLE)


def unnamed(_request: Request[Any, Any, Any], exc: AuthNameError) -> Response[dict[str, str]]:
    """A name that is not a plain account name."""
    return Response({"detail": exc.message}, status_code=HTTP_400_BAD_REQUEST)


class Segments(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """The segments an account reads beyond the tenant's general documents, whole."""

    segments: frozenset[str]


class Delegate(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """Whether an account acts for the people it serves."""

    delegate: bool


##### HANDLERS #####
async def me(caller: NamedDependency[Caller]) -> Caller:
    """Who the caller's key names: an account, or nobody."""
    return caller


async def listed(auth: NamedDependency[AuthEngine]) -> list[Account]:
    """Every account, the admin's included."""
    return await auth.accounts()


async def rotate(name: FromPath[str], auth: NamedDependency[AuthEngine]) -> Issued:
    """The account of `name`, made when missing, with one fresh key; every earlier one revoked."""
    return await auth.rotate(name)


async def segment(name: FromPath[str], data: JSONBody[Segments], auth: NamedDependency[AuthEngine]) -> Account:
    """The segments the account of `name` reads, set whole."""
    return await auth.segment(name, data.segments)


async def delegate(name: FromPath[str], data: JSONBody[Delegate], auth: NamedDependency[AuthEngine]) -> Account:
    """Whether the account of `name` acts for the people it serves, naming each call's subject."""
    return await auth.delegate(name, delegate=data.delegate)


async def revoke(name: FromPath[str], auth: NamedDependency[AuthEngine]) -> Revoked:
    """Every key of the account of `name` revoked."""
    return Revoked(name=name, revoked=await auth.revoke(name))


##### CHAINS #####
DEPS: Final[dict[str, Provide]] = {
    DepKey.GRAPH.value: Provide(graph, sync_to_thread=False),
    DepKey.AUTH.value: Provide(auth, sync_to_thread=False),
    DepKey.CALLER.value: Provide(caller, sync_to_thread=False),
}
OPTIONS: Final[dict[str, Any]] = {
    "tags": ["auth"],
    "dependencies": DEPS,
    "exception_handlers": {AuthClosedError: closed, AuthNameError: unnamed},
    "opt": OPT[Access.ADMIN],
    "security": SECURITY,
}
### who the caller is: any caller's question.
ANYONE: Final[dict[str, Any]] = {**OPTIONS, "opt": OPT[Access.ANONYMOUS]}

##### ROUTES #####
ROUTES: tuple[HTTPRouteHandler, ...] = (
    get("/auth/me", name="auth.me", **ANYONE)(me),
    get("/auth/accounts", name="auth.list", **OPTIONS)(listed),
    post("/auth/accounts/{name:str}/token", name="auth.rotate", status_code=HTTP_200_OK, **OPTIONS)(rotate),
    delete("/auth/accounts/{name:str}/token", name="auth.revoke", status_code=HTTP_200_OK, **OPTIONS)(revoke),
    put("/auth/accounts/{name:str}/segments", name="auth.segment", status_code=HTTP_200_OK, **OPTIONS)(segment),
    put("/auth/accounts/{name:str}/delegate", name="auth.delegate", status_code=HTTP_200_OK, **OPTIONS)(delegate),
)
