"""providers/drivers/cache/postgres: a durable cache in a Postgres database — it rides a `DatabasePort`, whichever driver.

Values of type T under a namespace in the database's `cache` table, shared by every process of the service. The
database is the lifespan's to open and close, not this cache's."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING, ClassVar, Final, Self

import msgspec

from e_infra.ports.provider import Isolation, Locality, ProviderSpec, Workload

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import timedelta

    from e_infra.ports.database import DatabasePort

CACHE_SCHEMA: Final[str] = (
    "CREATE TABLE IF NOT EXISTS cache (namespace text NOT NULL, key text NOT NULL, value bytea NOT NULL, "
    "expires timestamptz, PRIMARY KEY (namespace, key))"
)
CACHE_GET: Final[str] = (
    "SELECT key, value FROM cache WHERE namespace = $1 AND key = ANY($2) AND (expires IS NULL OR expires > now())"
)
CACHE_PUT: Final[str] = (
    "INSERT INTO cache (namespace, key, value, expires) VALUES ($1, $2, $3, $4) "
    "ON CONFLICT (namespace, key) DO UPDATE SET value = EXCLUDED.value, expires = EXCLUDED.expires"
)


##### DRIVER #####
class CachePostgresDriver[T]:
    """Values of type `kind` under `namespace` in the database's `cache` table — durable, shared by every process —,
    each kept `ttl` (None: until replaced). A value is msgpack; a row that no longer decodes (the type changed) is a
    miss, and a read skips what expired. The table is logged: what it keeps is often a paid answer."""

    spec: ClassVar[ProviderSpec] = ProviderSpec("cache-postgres", Locality.REMOTE, Workload.IO_BOUND, Isolation.LOOP)

    __slots__ = ("_db", "_decoder", "_encoder", "_namespace", "_ttl")

    def __init__(self, db: DatabasePort, namespace: str, kind: type[T], ttl: timedelta | None = None) -> None:
        self._db = db
        self._namespace = namespace
        self._ttl = ttl
        self._encoder = msgspec.msgpack.Encoder()
        self._decoder = msgspec.msgpack.Decoder(kind)

    ##### PRIVATE #####

    def _common_decoded(self, value: bytes) -> T | None:
        try:
            return self._decoder.decode(value)
        except msgspec.DecodeError:
            return None

    def _common_expires(self) -> datetime | None:
        return datetime.now(UTC) + self._ttl if self._ttl else None

    ############################################################

    ##### PUBLIC #####

    async def __aenter__(self) -> Self:
        await self._db.execute(CACHE_SCHEMA)
        return self

    async def __aexit__(self, *exc: object) -> None:
        """The database is the lifespan's to close, not this cache's."""

    async def health(self) -> bool:
        return await self._db.health()

    async def get(self, key: str) -> T | None:
        return (await self.many([key])).get(key)

    async def many(self, keys: Sequence[str]) -> dict[str, T]:
        rows = await self._db.fetch(CACHE_GET, [self._namespace, list(keys)]) if keys else []
        return {row["key"]: value for row in rows if (value := self._common_decoded(row["value"])) is not None}

    async def put(self, key: str, value: T) -> None:
        await self.put_many({key: value})

    async def put_many(self, items: Mapping[str, T]) -> None:
        expires = self._common_expires()
        rows = [[self._namespace, key, self._encoder.encode(value), expires] for key, value in items.items()]
        _ = rows and await self._db.many(CACHE_PUT, rows)
