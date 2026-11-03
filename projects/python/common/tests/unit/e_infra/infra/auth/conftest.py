"""tests/unit/e_infra/infra/auth: the auth package on a bare app — a router per access behind the guard, the token
middleware over a fake store.

`keys` is the store with `ana` (an account) and `root` (the admin) holding keys `t-ana` and `t-root`; `app` the app whose
sealed state holds the engine, as a lifespan leaves it; `client` runs it. `who` answers the caller a route saw, `open`
is a route kept out of authentication."""

from typing import TYPE_CHECKING, Any

import pytest
from litestar import Litestar, Request, get
from litestar.datastructures import State
from litestar.middleware import DefineMiddleware
from litestar.router import Router
from litestar.testing import AsyncTestClient

from e_infra.engines.auth import AuthEngine
from e_infra.infra.auth.guard import OPT, guard
from e_infra.infra.auth.middleware import EXCLUDED, TokenMiddleware
from e_infra.infra.auth.models import Access, Caller, Role
from e_infra.infra.config.base import Secret
from e_infra.infra.config.engines.auth import AuthSettings
from support.auth import FakeAuth

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@get("/who", sync_to_thread=False)
def who(request: Request[Caller, None, Any]) -> dict[str, str]:
    return {"name": request.user.name, "role": request.user.role}


@get("/open", opt={EXCLUDED: True}, sync_to_thread=False)
def opened(request: Request[Any, Any, Any]) -> dict[str, bool]:
    return {"resolved": request.scope.get("user") is not None}


@get("/undeclared", sync_to_thread=False)
def undeclared() -> dict[str, bool]:
    return {"reached": True}


def router(access: Access) -> Router:
    """A router whose one route `/<access>` answers, at the access given."""

    @get(f"/{access}", sync_to_thread=False)
    def route() -> dict[str, bool]:
        return {"reached": True}

    return Router(path="/", route_handlers=[route], opt=OPT[access], guards=[guard])


@pytest.fixture
def keys() -> FakeAuth:
    store = FakeAuth()
    store.key("t-ana", "ana")
    store.key("t-root", "root", Role.ADMIN)
    return store


@pytest.fixture
def app(keys: FakeAuth) -> Litestar:
    engine = AuthEngine(keys, AuthSettings(secret=Secret("k")))
    return Litestar(
        route_handlers=[
            who,
            opened,
            Router(path="/", route_handlers=[undeclared], guards=[guard]),
            *(router(access) for access in Access),
        ],
        middleware=[DefineMiddleware(TokenMiddleware, locate=lambda app: app.state["auth"])],
        state=State({"auth": engine}),
    )


@pytest.fixture
async def client(app: Litestar) -> AsyncIterator[AsyncTestClient[Litestar]]:
    async with AsyncTestClient(app) as running:
        yield running
