"""tests/conftest: the services behind the live app, faked for every tier — env seeded before the lazy infra singletons ever
load, redis answering from fakeredis, Postgres from the scripted pool of `tests/support/psqlpy`, the accounts and keys from
the dicts of `tests/support/auth`.

`os.environ` stays untouched at module import (doctrine: no side-effect between imports); the seeding
rides `pytest_configure`, which pytest runs before collection. Collection matters: pytest probes every
test-module global for `__test__` (anyio's hook calls `getattr(obj, "__test__", False)`), so a test
module holding `settings as st` at module level touches the LazyProxy during collection — the earliest
point any settings access can happen, and the reason a session fixture is already too late."""

import os
import tempfile
from pathlib import Path

import fakeredis
import fakeredis.aioredis
import pytest

from e_api.api.lifespan import providers as providers_module
from infra.auth.models import Role
from providers.drivers.database import psqlpy as psqlpy_module
from providers.drivers.store import redis as redis_module
from support.auth import FakeAuth
from support.psqlpy import FakePsqlpyServer


def pytest_configure(config: pytest.Config) -> None:
    """Seed the secrets and a private DB_PATH before any collection-time settings touch; external env wins."""
    ### the xdist controller collects nothing, and what it exports its workers would all share: only a process that runs
    ### tests seeds its own file.
    if config.getoption("dist", "no") != "no" and not hasattr(config, "workerinput"):
        return
    os.environ.setdefault("CRYPTO__SECRET", "unit-test-secret-0123456789")
    os.environ.setdefault("AUTH_SECRET", "unit-test-auth-secret-0123456789")
    os.environ.setdefault("DB_PATH", str(Path(tempfile.mkdtemp(prefix="e-api-tests-")) / "test.db"))


@pytest.fixture(autouse=True)
def redis_server(monkeypatch: pytest.MonkeyPatch) -> fakeredis.FakeServer:
    """The redis every driver of the test talks to: an in-memory server, `connected = False` takes it down."""
    server = fakeredis.FakeServer()
    monkeypatch.setattr(
        redis_module.redis, "from_url", lambda _url, **_kwargs: fakeredis.aioredis.FakeRedis(server=server)
    )
    return server


@pytest.fixture(autouse=True)
def psqlpy(monkeypatch: pytest.MonkeyPatch) -> FakePsqlpyServer:
    """The Postgres the db lifespan provisions on: scripted rows and recorded SQL, no database."""
    server = FakePsqlpyServer()
    monkeypatch.setattr(psqlpy_module, "ConnectionPool", server.pool)
    return server


@pytest.fixture(autouse=True)
def keys(monkeypatch: pytest.MonkeyPatch) -> FakeAuth:
    """The accounts and keys of the test: the lifespan opens this store where it would open Postgres."""
    store = FakeAuth()
    store.key("t-ana", "ana")
    store.key("t-root", "root", Role.ADMIN)
    monkeypatch.setattr(providers_module, "PostgresAuthDriver", lambda _database: store)
    return store
