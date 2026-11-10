"""tests/unit/e_api: the live app on the real graph, a request away — `client` over the faked services of `tests/conftest`
(`keys`: `ana` an account, `root` the admin; `ana_key` and `root_key` the `Authorization` headers that carry theirs), its
user records wiped, and what the access log wrote, recorded."""

from typing import TYPE_CHECKING, Any

import pytest
from litestar.testing import TestClient

from e_api.api import middlewares as middlewares_module
from e_api.api.deps import USER_KEY
from e_api.main import create_app
from support.logs import RequestLogs

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def request_logs(monkeypatch: pytest.MonkeyPatch) -> RequestLogs:
    """The access log's logger replaced by a recorder for the test's length."""
    recorder = RequestLogs()
    monkeypatch.setattr(middlewares_module, "logger", recorder)
    return recorder


@pytest.fixture
def ana_key() -> dict[str, str]:
    return {"Authorization": "Bearer t-ana"}


@pytest.fixture
def root_key() -> dict[str, str]:
    return {"Authorization": "Bearer t-root"}


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        store = test_client.app.state.system.providers.store

        async def wipe() -> None:
            ### one shared file per process: every test starts from empty; keys() streams, so drain it async.
            [await store.delete(key) async for key in store.keys(USER_KEY)]

        with test_client.portal() as portal:
            portal.call(wipe)
        yield test_client


@pytest.fixture
def created_user(client: TestClient, root_key: dict[str, str]) -> dict[str, Any]:
    response = client.post(
        "/users",
        json={
            "username": "alice",
            "email": "alice@example.com",
            "password": "correct-horse-1",
            "quota": "12.50",
        },
        headers=root_key,
    )
    assert response.status_code == 201, response.text
    return response.json()
