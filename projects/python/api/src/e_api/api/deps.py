"""api.deps: chained dependency providers — litestar resolves the graph recursively per request.

No FastAPI `Depends()` sugar: binding is by *name*. Each link declares what it consumes in its own
signature (`store` takes `graph`), every route wires the chains it uses in a local `dependencies` mapping, and the app
itself registers nothing. Links run once per request, in resolved order; independent links run concurrently.

Who may reach a route is `infra/auth/guard`'s, the same check the MCP door's tools pass; `caller` hands the user the
token middleware resolved to the handlers that take it.
"""

from enum import StrEnum, auto
from typing import Any

import msgspec
from asgi_correlation_id import correlation_id as correlation_id_var
from litestar.connection import Request
from litestar.di import NamedDependency

from e_api.api.state import AppState
from e_api.engines.auth import AuthEngine
from e_api.infra.auth.models import Caller
from e_api.infra.state import State
from e_api.models.user import User, UserRecord
from e_api.ports.store import StorePort

USER_KEY: str = "user:"


##### DEPENDENCY KEYS — the wiring vocabulary: a typo is an attribute error at import, never a silent runtime miss #####
class DepKey(StrEnum):
    GRAPH = auto()
    STORE = auto()
    AUTH = auto()
    CALLER = auto()
    CORRELATION_ID = auto()


##### LINKS — each names its injection parameter and consumes other links by name #####
def graph(state: AppState) -> State:
    """Root of every chain: the app's system graph, filled by the lifespans and sealed — read off Litestar's
    reserved `state`, which Litestar builds as `AppState` itself."""
    return state.system


def store(graph: NamedDependency[State]) -> StorePort:
    """The KV edge the user records live on; swap scope here to send a route elsewhere. Chain: graph."""
    return graph.providers.store


def auth(graph: NamedDependency[State]) -> AuthEngine:
    """Who is asking, and the accounts and keys the admin manages. Chain: graph."""
    return graph.engines.auth


def caller(request: Request[Caller, None, Any]) -> Caller:
    """Who is asking: the user the token middleware resolved, carried into the handler. Chain: request."""
    return request.user


def correlation_id() -> str:
    """Request id propagated by `CorrelationIdMiddleware`; empty only when the middleware is off. Chain: none."""
    return correlation_id_var.get() or ""


##### HELPERS — shared by handlers and links, never injected #####
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
