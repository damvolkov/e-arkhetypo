"""api.deps: chained dependency providers — litestar resolves the graph recursively per request.

No FastAPI `Depends()` sugar: binding is by *name*. Each link declares what it consumes in its own
signature (`oauth` and `store` take `graph`, `current_user` takes `request` + `store`), every route
wires the chains it uses in a local `dependencies` mapping, and the app itself registers nothing.
Links run once per request, in resolved order; independent links run concurrently.
"""

from enum import StrEnum, auto

import msgspec
from asgi_correlation_id import correlation_id as correlation_id_var
from authlib.integrations.starlette_client import OAuth
from litestar.connection import Request
from litestar.di import NamedDependency
from litestar.exceptions import NotAuthorizedException

from adapters.ports import StorePort
from core.state import State
from e_api.api.security import bearer_claims
from e_api.api.state import AppState
from e_api.models.user import User, UserRecord

USER_KEY: str = "user:"

type ClaimValue = str | int | float | list[str] | None


##### DEPENDENCY KEYS — the wiring vocabulary: a typo is an attribute error at import, never a silent runtime miss #####
class DepKey(StrEnum):
    GRAPH = auto()
    STORE = auto()
    CURRENT_USER = auto()
    CORRELATION_ID = auto()
    OAUTH = auto()


##### LINKS — each names its injection parameter and consumes other links by name #####
def graph(state: AppState) -> State:
    """Root of every chain: the app's system graph, filled by the lifespans and sealed — read off Litestar's
    reserved `state`, which Litestar builds as `AppState` itself."""
    return state.system


def oauth(graph: NamedDependency[State]) -> OAuth:
    """The authlib registry — empty while no IdP is configured. Chain: graph."""
    return graph.oauth


def store(graph: NamedDependency[State]) -> StorePort:
    """The KV edge the user records live on; swap scope here to send a route elsewhere. Chain: graph."""
    return graph.adapters.store


async def current_user(request: Request, store: NamedDependency[StorePort]) -> User:
    """The placeholder authz: bearer claims (guard already verified) mapped to a live `User`.

    Chain: request + store. Swap the lookup for the real session when it exists."""
    claims: dict[str, ClaimValue] = bearer_claims(request)
    match await load_record(store, str(claims.get("sub", ""))):
        case None:
            raise NotAuthorizedException(detail="Unknown subject")
        case record:
            return to_user(record)


def correlation_id() -> str:
    """Request id propagated by `CorrelationIdMiddleware`; empty only when the middleware is off. Chain: none."""
    return correlation_id_var.get() or ""


##### HELPERS — shared by handlers and links, never injected #####
def registered_providers(oauth: OAuth) -> list[str]:
    """Sorted identities registered with authlib: the single public read edge over its private registry."""
    ### authlib exposes no public accessor for `_registry`; leaking it to routers would spread the coupling, it stops here.
    return sorted(oauth._registry)


async def load_record(store: StorePort, user_id: str) -> UserRecord | None:
    """Single point where a user is read from the KV store; None means gone."""
    raw = await store.get(f"{USER_KEY}{user_id}")
    return None if raw is None else msgspec.json.decode(raw, type=UserRecord)


def to_user(record: UserRecord) -> User:
    """Projection: the credential is lost by construction — `User` has no hash field to drop."""
    return User(
        id=record.id,
        username=record.username,
        email=record.email,
        birth=record.birth,
        quota=record.quota,
        created=record.created,
    )
