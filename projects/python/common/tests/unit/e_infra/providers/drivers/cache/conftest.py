"""tests/unit/e_infra/providers/drivers/cache: a `DatabasePort` that keeps the cache table in a dict.

`FakeDatabase` answers the three statements the cache runs — create, get, put — by identity, honouring namespace, key
and expiry as the SQL does; `down` makes every call fail as a database that went away."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, ClassVar, Self

import pytest

from e_infra.infra.errors import DatabaseError
from e_infra.ports.provider import Isolation, Locality, ProviderSpec, Workload
from e_infra.providers.drivers.cache.postgres import CACHE_GET, CACHE_PUT, CACHE_SCHEMA

if TYPE_CHECKING:
    from collections.abc import Sequence
    from contextlib import AbstractAsyncContextManager

    from e_infra.ports.database import QueryPort, Row


class FakeDatabase:
    """Rows of the cache table by (namespace, key): value bytes and expiry."""

    spec: ClassVar[ProviderSpec] = ProviderSpec("fake-db", Locality.EMBEDDED, Workload.IO_BOUND, Isolation.LOOP)

    def __init__(self) -> None:
        self.table: dict[tuple[str, str], tuple[bytes, datetime | None]] = {}
        self.created = 0
        self.down = False

    def _check(self) -> None:
        if self.down:
            msg = "connection reset"
            raise DatabaseError(msg)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Nothing to release."""

    async def health(self) -> bool:
        return not self.down

    async def execute(self, query: str, params: Sequence[object] = ()) -> None:
        self._check()
        self.created += query == CACHE_SCHEMA

    async def fetch(self, query: str, params: Sequence[object] = ()) -> list[Row]:
        self._check()
        namespace, keys = params
        now = datetime.now(UTC)
        return [
            {"key": key, "value": value}
            for (held, key), (value, expires) in self.table.items()
            if query == CACHE_GET and held == namespace and key in keys and (expires is None or expires > now)  # ty: ignore[unsupported-operator]
        ]

    async def row(self, query: str, params: Sequence[object] = ()) -> Row | None:
        return next(iter(await self.fetch(query, params)), None)

    async def many(self, query: str, params: Sequence[Sequence[object]]) -> None:
        self._check()
        rows: list[Any] = [*params] if query == CACHE_PUT else []
        self.table |= {(namespace, key): (value, expires) for namespace, key, value, expires in rows}

    def transaction(self) -> AbstractAsyncContextManager[QueryPort]:
        raise NotImplementedError


@pytest.fixture
def db() -> FakeDatabase:
    return FakeDatabase()
