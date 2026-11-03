"""tests/unit/e_api/mcp: the MCP door as a client meets it — the real app over the fake accounts and the in-memory store, its
endpoint reached by the SDK's own client (`support/mcp`): none is nobody, `ana_key` and `root_key` carry the keys of an
account and the admin.

`client` here is the async one the SDK client needs (the lifespans run for the test's length), its user records wiped;
`connect` opens the SDK client on `/mcp`."""

from typing import TYPE_CHECKING

import pytest
from litestar.testing import AsyncTestClient

from e_api.api.deps import USER_KEY
from e_api.main import create_app
from support.mcp import BASE, connect

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from litestar import Litestar

__all__ = ["app", "client", "connect"]


@pytest.fixture
def app() -> Litestar:
    return create_app()


@pytest.fixture
async def client(app: Litestar) -> AsyncIterator[AsyncTestClient[Litestar]]:
    async with AsyncTestClient(app, base_url=BASE) as running:
        store = running.app.state.system.providers.store
        ### one shared file per process: every test starts from empty; keys() streams, so drain it async.
        _ = [await store.delete(key) async for key in store.keys(USER_KEY)]
        yield running
