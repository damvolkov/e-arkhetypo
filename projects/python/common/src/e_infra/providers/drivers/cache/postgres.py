"""providers/drivers/cache/postgres: a durable cache in a Postgres database — it rides a `DatabasePort`, whichever driver.

Values of type T under a namespace in the database's `cache` table, shared by every process of the service. The
database is the lifespan's to open and close, not this cache's. Opening creates the table under a transaction-level
advisory lock: `CREATE TABLE IF NOT EXISTS` alone races between instances opening at once. Every refusal at its
border — the database's, or a value msgspec cannot encode — is a `CacheError`, so the engine above degrades on it and
never fails its caller."""

from contextlib import contextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, ClassVar, Final, Self

import msgspec

from e_infra.infra.errors import CacheError, DatabaseError, ProviderError
from e_infra.infra.logger import logger
from e_infra.ports.provider import Isolation, Locality, ProviderSpec, Workload

if TYPE_CHECKING:
    from collections.abc import Generator, Mapping, Sequence
    from datetime import timedelta

    from e_infra.ports.database import DatabasePort

CACHE_SCHEMA: Final[str] = (
    "CREATE TABLE IF NOT EXISTS cache (namespace text NOT NULL, key text NOT NULL, value bytea NOT NULL, "
    "expires timestamptz, PRIMARY KEY (namespace, key))"
)
### the table is created by one opener at a time: two concurrent creators collide on `pg_type`.
CACHE_LOCK: Final[str] = "SELECT pg_advisory_xact_lock(hashtext('cache'))"
CACHE_GET: Final[str] = (
    "SELECT key, value FROM cache WHERE namespace = $1 AND key = ANY($2) AND (expires IS NULL OR expires > now())"
)
CACHE_PUT: Final[str] = (
    "INSERT INTO cache (namespace, key, value, expires) VALUES ($1, $2, $3, $4) "
    "ON CONFLICT (namespace, key) DO UPDATE SET value = EXCLUDED.value, expires = EXCLUDED.expires"
)


##### WIRE #####
class PostgresEntry(msgspec.Struct, frozen=True):
    """The slice of a `cache` row this driver reads."""

    key: str
    value: bytes


##### DRIVER #####
class PostgresCacheDriver[T]:
    """Values of type `kind` under `namespace` in the database's `cache` table — durable, shared by every process —,
    each kept `ttl` (None: until replaced). A value is msgpack; a row that no longer decodes (the type changed) is a
    miss, and a read skips what expired. The table is logged: what it keeps is often a paid answer."""

    spec: ClassVar[ProviderSpec] = ProviderSpec("cache-postgres", Locality.REMOTE, Workload.IO_BOUND, Isolation.LOOP)

    __slots__ = ("_db", "_decoder", "_encoder", "_namespace", "_ttl")

    def __init__(self, db: DatabasePort, namespace: str, kind: type[T], *, ttl: timedelta | None) -> None:
        self._ttl = ttl
        self._db = db
        self._namespace = namespace
        self._encoder = msgspec.msgpack.Encoder()
        self._decoder = msgspec.msgpack.Decoder(kind)

    ##### PRIVATE #####

    @staticmethod
    @contextmanager
    def _common_guard() -> Generator[None]:
        """The database's own `DatabaseError`, as the cache's `CacheError`."""
        try:
            yield
        except DatabaseError as error:
            logger.error("cache postgres failed", error=str(error))
            raise CacheError(str(error)) from error

    def _put_encoded(self, value: T) -> bytes:
        """A value as msgpack; one msgspec cannot encode is the cache's `CacheError`, like any refusal at its border."""
        try:
            return self._encoder.encode(value)
        ### msgspec raises TypeError for a type it does not know, EncodeError for a value it cannot write.
        except (msgspec.EncodeError, TypeError) as error:
            logger.error("cache postgres encode failed", namespace=self._namespace, error=str(error))
            raise CacheError(str(error)) from error

    def _common_decoded(self, value: bytes) -> T | None:
        try:
            return self._decoder.decode(value)
        except msgspec.DecodeError as error:
            logger.warning("cache postgres row skipped", namespace=self._namespace, error=str(error))
            return None

    def _common_expires(self) -> datetime | None:
        return datetime.now(UTC) + self._ttl if self._ttl else None

    ############################################################

    ##### PUBLIC #####

    async def __aenter__(self) -> Self:
        with self._common_guard():
            async with self._db.transaction() as tx:
                await tx.execute(CACHE_LOCK)
                await tx.execute(CACHE_SCHEMA)
        logger.info("cache postgres opened", namespace=self._namespace)
        return self

    async def __aexit__(self, *exc: object) -> None:
        """The database is the lifespan's to close, not this cache's."""
        logger.info("cache postgres closed", namespace=self._namespace)

    async def health(self) -> bool:
        try:
            return await self._db.health()
        except ProviderError as error:
            logger.warning("cache postgres unhealthy", namespace=self._namespace, error=str(error))
            raise

    async def get(self, key: str) -> T | None:
        return (await self.many([key])).get(key)

    async def many(self, keys: Sequence[str]) -> dict[str, T]:
        logger.debug("cache postgres many", namespace=self._namespace, keys=len(keys))
        with self._common_guard():
            rows = await self._db.fetch(CACHE_GET, [self._namespace, list(keys)]) if keys else []
        entries = [msgspec.convert(row, PostgresEntry) for row in rows]
        return {entry.key: value for entry in entries if (value := self._common_decoded(entry.value)) is not None}

    async def put(self, key: str, value: T) -> None:
        await self.put_many({key: value})

    async def put_many(self, items: Mapping[str, T]) -> None:
        expires = self._common_expires()
        rows = [[self._namespace, key, self._put_encoded(value), expires] for key, value in items.items()]
        logger.debug("cache postgres put many", namespace=self._namespace, keys=len(rows))
        with self._common_guard():
            _ = rows and await self._db.many(CACHE_PUT, rows)
