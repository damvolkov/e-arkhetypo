"""ports/store: a byte-keyed store — point reads, writes, deletes and a lazy key scan, the whole CRUD a consumer sees."""

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from e_infra.ports.provider import Provider

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@runtime_checkable
class StorePort(Provider, Protocol):
    """Byte-keyed store: swapping redis for sqlite edits one wiring line, zero consumer code."""

    async def get(self, key: str) -> bytes | None:
        """Missing key reads as None, never an exception."""
        ...

    async def set(self, key: str, value: bytes) -> None: ...

    async def delete(self, key: str) -> None:
        """Missing key is a no-op."""
        ...

    def keys(self, prefix: str = "") -> AsyncIterator[str]:
        """Keys starting with `prefix`, streamed lazily: an async generator, never a materialized list."""
        ...
