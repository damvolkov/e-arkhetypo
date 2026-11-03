"""tests/unit/e_infra/providers/drivers/store/redis: the KV contract on fakeredis — SCAN streamed, never KEYS."""

from typing import TYPE_CHECKING

import pytest

from e_infra.infra.config.providers.drivers.store.redis import RedisSettings
from e_infra.infra.errors import StoreError
from e_infra.ports.store import StorePort
from e_infra.providers.drivers.store.redis import RedisDriver
from support.kv import KV_CALLS

if TYPE_CHECKING:
    from typing import Any

    import fakeredis

    from unit.e_infra.conftest import Logs

pytestmark = pytest.mark.usefixtures("redis_calls")


async def test_redis_meets_the_store_port(driver: RedisDriver) -> None:
    assert isinstance(driver, StorePort)
    assert driver.spec.name == "redis"


async def test_redis_open_asks_for_its_client_with_the_settings_and_close_is_idempotent(
    driver: RedisDriver, redis_calls: list[tuple[str, dict[str, Any]]], logs: Logs
) -> None:
    async with driver:
        pass
    await driver.__aexit__(None, None, None)
    assert redis_calls == [
        ("redis://:hunter2@fake:6379/1", {"max_connections": 3, "socket_timeout": 2.0, "socket_connect_timeout": 2.0})
    ]
    assert logs.at("info") == ["redis opened", "redis closed"]
    assert "hunter2" not in repr(logs.events)


async def test_redis_default_settings_come_from_the_composer(redis_calls: list[tuple[str, dict[str, Any]]]) -> None:
    async with RedisDriver():
        assert redis_calls[0][1]["max_connections"] == RedisSettings().pool


async def test_redis_kv_cycle(driver: RedisDriver) -> None:
    async with driver:
        await driver.set("user:1", b"one")
        await driver.set("user:2", b"two")
        await driver.set("other:1", b"x")
        assert (await driver.get("user:1"), await driver.get("missing")) == (b"one", None)
        assert sorted([key async for key in driver.keys("user:")]) == ["user:1", "user:2"]
        await driver.delete("user:1")
        assert await driver.get("user:1") is None


async def test_redis_unopened_calls_are_store_errors(driver: RedisDriver) -> None:
    with pytest.raises(StoreError, match="not open"):
        await driver.get("anything")
    assert not await driver.health()


async def test_redis_health_true_then_false_and_warned_when_the_server_goes(
    driver: RedisDriver, redis_server: fakeredis.FakeServer, logs: Logs
) -> None:
    async with driver:
        assert await driver.health()
        redis_server.connected = False
        assert not await driver.health()
    assert logs.at("warning") == ["redis unhealthy"]


@pytest.mark.parametrize("call", KV_CALLS)
async def test_redis_errors_are_translated_and_logged(
    driver: RedisDriver, redis_server: fakeredis.FakeServer, logs: Logs, call: str
) -> None:
    async with driver:
        redis_server.connected = False
        with pytest.raises(StoreError):
            await KV_CALLS[call](driver)
    assert logs.at("error") == ["redis failed"]
