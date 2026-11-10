"""tests/unit/e_infra/ports/provider: the spec is frozen orienting data; every provider satisfies its port by shape."""

from dataclasses import FrozenInstanceError
from typing import TYPE_CHECKING

import pytest

from e_infra.infra.errors import StoreError
from e_infra.ports.http import HTTPPort
from e_infra.ports.provider import Isolation, Locality, Opened, Provider, ProviderSpec, Workload
from e_infra.ports.store import StorePort
from e_infra.providers.drivers.http.wreq import WreqDriver
from e_infra.providers.drivers.store.redis import RedisDriver
from e_infra.providers.drivers.store.sqlite import SqliteDriver
from unit.e_infra.conftest import redis_args, sqlite_args, wreq_args

if TYPE_CHECKING:
    from pathlib import Path


def test_spec_is_frozen_and_defaults_are_conservative() -> None:
    spec = ProviderSpec("x", Locality.REMOTE, Workload.IO_BOUND, Isolation.LOOP)
    assert (spec.fork_safe, spec.pooled, spec.warmup, spec.memory_hint_mb) == (False, False, False, None)
    with pytest.raises(FrozenInstanceError):
        spec.name = "y"  # ty: ignore[invalid-assignment]


@pytest.mark.parametrize("axis", [Locality, Workload, Isolation])
def test_axes_are_string_enums(axis: type[Locality | Workload | Isolation]) -> None:
    assert all(str(member) == member.value == member.name.lower() for member in axis)


async def test_sqlite_satisfies_store(tmp_path: Path) -> None:
    driver = SqliteDriver(**sqlite_args(path=tmp_path / "kv.db"))
    assert (isinstance(driver, StorePort), isinstance(driver, Provider)) == (True, True)


async def test_redis_satisfies_store() -> None:
    assert isinstance(RedisDriver(**redis_args()), StorePort)


async def test_http_satisfies_client() -> None:
    assert isinstance(WreqDriver(**wreq_args()), HTTPPort)


async def test_a_class_without_lifecycle_is_no_provider() -> None:
    class Bare:
        spec = ProviderSpec("bare", Locality.EMBEDDED, Workload.MIXED, Isolation.LOOP)

    assert not isinstance(Bare(), Provider)


async def test_opened_raises_the_provider_error_before_open_and_after_close(tmp_path: Path) -> None:
    driver = SqliteDriver(**sqlite_args(path=tmp_path / "kv.db"))
    with pytest.raises(StoreError, match="SqliteDriver is not open"):
        _ = driver.db
    async with driver:
        assert await (await driver.db.execute("SELECT 1")).fetchone() == (1,)
    with pytest.raises(StoreError, match="SqliteDriver is not open"):
        _ = driver.db


def test_opened_read_on_the_class_is_the_descriptor() -> None:
    assert isinstance(SqliteDriver.db, Opened)
