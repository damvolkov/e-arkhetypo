"""tests/unit/e_infra/infra/mcp: the MCP engine as a client meets it — a probe door (`support/tools`) on an app whose
keys are a fake auth store, reached by the SDK's own client: none is nobody, `ana` and `root` send their keys.

`app` is the probe app, `client` runs its lifespans, `connect` is the SDK client on `/mcp`; `ana` and `root` are the
`Authorization` headers of an account and the admin."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from litestar.testing import AsyncTestClient

from e_infra.engines.auth import AuthEngine
from e_infra.infra.auth.models import Role
from support.auth import FakeAuth
from support.mcp import connect
from support.tools import build
from unit.e_infra.conftest import auth_args

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from litestar import Litestar

__all__ = ["Detached", "ana", "app", "client", "connect", "detached", "root"]


@dataclass(frozen=True, slots=True)
class Detached:
    """A tool call's context with no HTTP request behind it, as an in-process transport hands it."""

    request: None = None


@pytest.fixture
def keys() -> FakeAuth:
    store = FakeAuth()
    store.key("t-ana", "ana")
    store.key("t-root", "admin", Role.ADMIN)
    return store


@pytest.fixture
def app(keys: FakeAuth) -> Litestar:
    return build(AuthEngine(keys, **auth_args()))


@pytest.fixture
async def client(app: Litestar) -> AsyncIterator[AsyncTestClient[Litestar]]:
    async with AsyncTestClient(app) as running:
        yield running


@pytest.fixture
def ana() -> dict[str, str]:
    return {"Authorization": "Bearer t-ana"}


@pytest.fixture
def root() -> dict[str, str]:
    return {"Authorization": "Bearer t-root"}


@pytest.fixture
def detached() -> Detached:
    return Detached()
