"""ports/cache: values of one type kept by key — a cache may forget, so a miss is never an error."""

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from e_infra.ports.provider import Provider

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


@runtime_checkable
class CachePort[T](Provider, Protocol):
    """`get` a value or None (absent or expired), `many` the values of the keys found, `put` one, `put_many` several.
    A value is never trusted past its time to live."""

    async def get(self, key: str) -> T | None: ...

    async def many(self, keys: Sequence[str]) -> dict[str, T]: ...

    async def put(self, key: str, value: T) -> None: ...

    async def put_many(self, items: Mapping[str, T]) -> None: ...
