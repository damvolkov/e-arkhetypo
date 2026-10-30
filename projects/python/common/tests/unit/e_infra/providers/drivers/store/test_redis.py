"""e_infra/providers/drivers/store/redis: the KV contract against a fake server — SCAN streamed, never KEYS."""

import fakeredis.aioredis
import pytest

from e_infra.infra.config.redis import RedisSettings
from e_infra.infra.errors import StoreError
from e_infra.ports.store import StorePort
from e_infra.providers.drivers.store import redis as redis_module
from e_infra.providers.drivers.store.redis import RedisDriver


async def test_redis_offline_contract() -> None:
    adapter = RedisDriver(RedisSettings(redis_url="redis://localhost:1/0"))  # never connected on purpose
    assert adapter.spec.name == "redis"
    with pytest.raises(StoreError, match="not open"):
        await adapter.get("anything")


async def test_redis_connected_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    """fakeredis answers from_url: the full KV cycle without a server, exactly as the lifespan would open it."""
    monkeypatch.setattr(redis_module.redis, "from_url", fakeredis.aioredis.FakeRedis.from_url)
    adapter = RedisDriver(RedisSettings(redis_url="redis://fake:6379/0"))
    async with adapter:
        assert isinstance(adapter, StorePort)
        await adapter.set("user:1", b"one")
        assert await adapter.get("user:1") == b"one"
        assert await adapter.get("missing") is None

        await adapter.set("user:2", b"two")
        assert sorted([key async for key in adapter.keys("user:")]) == ["user:1", "user:2"]

        await adapter.delete("user:1")
        assert await adapter.get("user:1") is None
    await adapter.__aexit__(None, None, None)  # idempotent, as with every provider


async def test_redis_health(monkeypatch: pytest.MonkeyPatch) -> None:
    """The protocol's own PING on the pool; before opening, nothing answers."""
    monkeypatch.setattr(redis_module.redis, "from_url", fakeredis.aioredis.FakeRedis.from_url)
    adapter = RedisDriver(RedisSettings(redis_url="redis://fake:6379/0"))
    assert not await adapter.health()
    async with adapter:
        assert await adapter.health()


async def test_redis_health_down() -> None:
    """A server nothing listens for: the pool opens lazily, so only the health finds it gone — and a read raises
    the tree's `StoreError`, never redis's."""
    async with RedisDriver(RedisSettings(redis_url="redis://127.0.0.1:9/0")) as adapter:
        assert not await adapter.health()
        with pytest.raises(StoreError):
            await adapter.get("k")
