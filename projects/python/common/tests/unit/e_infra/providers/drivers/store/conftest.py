"""tests/unit/e_infra/providers/drivers/store: redis on fakeredis — no server, a switch that takes it down.

`redis_server` is the shared fake server (`connected = False` makes every call fail as a server that went away);
`driver` is a `RedisDriver` over it, not yet open; `redis_calls` records how the driver asked `redis.from_url` for its client, which then answers from that server."""

from datetime import timedelta
from typing import Any

import fakeredis
import fakeredis.aioredis
import pytest

from e_infra.infra.config.base import Secret
from e_infra.infra.config.providers.drivers.store.redis import RedisSettings
from e_infra.providers.drivers.store import redis as redis_module
from e_infra.providers.drivers.store.redis import RedisDriver


@pytest.fixture
def redis_server() -> fakeredis.FakeServer:
    return fakeredis.FakeServer()


@pytest.fixture
def redis_calls(
    monkeypatch: pytest.MonkeyPatch, redis_server: fakeredis.FakeServer
) -> list[tuple[str, dict[str, Any]]]:
    """`(url, kwargs)` of every `redis.from_url` call: the driver is patched to get a fakeredis client from it."""
    calls: list[tuple[str, dict[str, Any]]] = []

    def from_url(url: str, **kwargs: Any) -> fakeredis.aioredis.FakeRedis:
        calls.append((url, kwargs))
        return fakeredis.aioredis.FakeRedis(server=redis_server)

    monkeypatch.setattr(redis_module.redis, "from_url", from_url)
    return calls


@pytest.fixture
def driver() -> RedisDriver:
    return RedisDriver(RedisSettings(url=Secret("redis://:hunter2@fake:6379/1"), pool=3, timeout=timedelta(seconds=2)))
