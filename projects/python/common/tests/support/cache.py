"""tests/support/cache: a `PostgresCacheDriver` over a database port, its time to live the only argument a test varies."""

from typing import TYPE_CHECKING

from e_infra.providers.drivers.cache.postgres import PostgresCacheDriver

if TYPE_CHECKING:
    from datetime import timedelta

    from e_infra.ports.database import DatabasePort


def cache(
    db: DatabasePort, kind: type = int, namespace: str = "unit", *, ttl: timedelta | None = None
) -> PostgresCacheDriver:
    return PostgresCacheDriver(db, namespace, kind, ttl=ttl)
