"""tests/unit/e_api: the live app on the real graph — env seeded before the lazy core singletons ever load.

`os.environ` stays untouched at module import (doctrine: no side-effect between imports); the seeding
rides `pytest_configure`, which pytest runs before collection. Collection matters: pytest probes every
test-module global for `__test__` (anyio's hook calls `getattr(obj, "__test__", False)`), so a test
module holding `settings as st` at module level touches the LazyProxy during collection — the earliest
point any settings access can happen, and the reason a session fixture is already too late."""

import os
import tempfile
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from litestar.testing import TestClient

from e_api.api.deps import USER_KEY
from e_api.main import create_app

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator


def pytest_configure() -> None:
    """Seed SECRET and a private DB_PATH before any collection-time settings touch; external env wins."""
    os.environ.setdefault("SECRET", "unit-test-secret-0123456789")
    os.environ.setdefault("DB_PATH", str(Path(tempfile.mkdtemp(prefix="e-api-tests-")) / "test.db"))


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        store = test_client.app.state.system.adapters.store

        async def wipe() -> None:
            ### one shared file per process: every test starts from empty; keys() streams, so drain it async.
            [await store.delete(key) async for key in store.keys(USER_KEY)]

        with test_client.portal() as portal:
            portal.call(wipe)
        yield test_client


@pytest.fixture
def bearer(client: TestClient) -> Callable[[str], dict[str, str]]:
    """Mint real tokens with the live crypto engine — the fake check accepts exactly what crypto signs."""

    def make(subject: str) -> dict[str, str]:
        token = client.app.state.system.crypto.create_token({"sub": subject}, expires_in=timedelta(minutes=5))
        return {"Authorization": f"Bearer {token}"}

    return make


@pytest.fixture
def created_user(client: TestClient) -> dict[str, Any]:
    response = client.post(
        "/users",
        json={
            "username": "alice",
            "email": "alice@example.com",
            "password": "correct-horse-1",
            "quota": "12.50",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()
