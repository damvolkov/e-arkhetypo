"""tests/support/app: the services behind the live app, faked — redis from fakeredis, Postgres from the scripted pool of
`support.psqlpy`, the accounts and keys from the dicts of `support.auth`. Every tier's conftest takes these fixtures."""

import fakeredis
import fakeredis.aioredis
import pytest

from e_api.api.lifespan import providers as providers_module
from infra.auth.models import Role
from providers.drivers.database import psqlpy as psqlpy_module
from providers.drivers.store import redis as redis_module
from support.auth import FakeAuth
from support.psqlpy import FakePsqlpyServer


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
