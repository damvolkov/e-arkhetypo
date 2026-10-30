"""tests/unit/e_infra/adapters/redis: the KV contract against a fake server — SCAN streamed, never KEYS."""

import fakeredis.aioredis
import pytest

from e_infra.adapters import redis as redis_module
from e_infra.adapters.base import PingError
from e_infra.adapters.redis import RedisAdapter
from e_infra.infra.config.redis import RedisSettings


async def test_redis_offline_contract() -> None:
    adapter = RedisAdapter(RedisSettings(redis_url="redis://localhost:1/0"))  # never connected on purpose
    assert adapter.name == "redis"
    with pytest.raises(RuntimeError, match="not connected"):
        await adapter.get("anything")


async def test_redis_connected_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    """fakeredis answers from_url: the full KV cycle without a server, exactly as the lifespan would open it."""
    monkeypatch.setattr(redis_module.redis, "from_url", fakeredis.aioredis.FakeRedis.from_url)
    adapter = RedisAdapter(RedisSettings(redis_url="redis://fake:6379/0"))
    async with adapter:
        await adapter.set("user:1", b"one")
        assert await adapter.get("user:1") == b"one"
        assert await adapter.get("missing") is None

        await adapter.set("user:2", b"two")
        assert sorted([key async for key in adapter.keys("user:")]) == ["user:1", "user:2"]

        await adapter.delete("user:1")
        assert await adapter.get("user:1") is None
    await adapter.close()  # idempotent, as with every member of the family


async def test_redis_ping(monkeypatch: pytest.MonkeyPatch) -> None:
    """The protocol's own PING on the pool; before connect, nothing answers."""
    monkeypatch.setattr(redis_module.redis, "from_url", fakeredis.aioredis.FakeRedis.from_url)
    adapter = RedisAdapter(RedisSettings(redis_url="redis://fake:6379/0"))
    with pytest.raises(PingError, match=r"^redis: RuntimeError: "):
        await adapter.ping()
    async with adapter:
        await adapter.ping()


async def test_redis_ping_down() -> None:
    """A server nothing listens for: the pool opens lazily, so only the ping finds it gone."""
    async with RedisAdapter(RedisSettings(redis_url="redis://127.0.0.1:9/0")) as adapter:
        with pytest.raises(PingError, match=r"^redis: ConnectionError: "):
            await adapter.ping()
