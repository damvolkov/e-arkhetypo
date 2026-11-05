"""ports/blob: an object store — bytes by key, every write a new generation, a conditional write the one lock.

A write may be unconditional (`if_generation=None`), create-only (`0`), or hold only on the generation the writer read:
two writers on one key, one wins, the other gets `BlobPreconditionError`. Keys are the caller's; a store may root them
under a prefix of its own (an environment, a test run) and never shows it."""

from typing import TYPE_CHECKING, Protocol, runtime_checkable

import msgspec

from e_infra.ports.provider import Provider

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class BlobMeta(msgspec.Struct, frozen=True, kw_only=True):
    """One object as the store holds it: its key, its generation (only ever grows), its size in bytes."""

    key: str
    generation: int
    size: int


@runtime_checkable
class BlobPort(Provider, Protocol):
    """`get` raises `BlobNotFoundError` for a missing key, `head` answers None; `list` walks a prefix lazily."""

    async def put(self, key: str, data: bytes, *, if_generation: int | None = None) -> BlobMeta: ...

    async def get(self, key: str) -> bytes: ...

    async def head(self, key: str) -> BlobMeta | None: ...

    def list(self, prefix: str) -> AsyncIterator[BlobMeta]: ...
