"""tests/support/cache: a `CachePostgresDriver` over a database port, its time to live the only setting a test varies."""

from typing import TYPE_CHECKING

from e_infra.infra.config.providers.drivers.cache.postgres import CachePostgresSettings
from e_infra.providers.drivers.cache.postgres import CachePostgresDriver

if TYPE_CHECKING:
    from datetime import timedelta

    from e_infra.ports.database import DatabasePort


def cache(
    db: DatabasePort, kind: type = int, namespace: str = "unit", *, ttl: timedelta | None = None
) -> CachePostgresDriver:
    return CachePostgresDriver(db, namespace, kind, CachePostgresSettings(ttl=ttl))
