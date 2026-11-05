"""tests/support/blob: `BlobPort` in memory — the second implementation of the contract, the double engine tests stand on.

Generations count up from one per write, as GCS's only ever grow; a precondition that does not hold is the port's own
`BlobPreconditionError`, a missing key `BlobNotFoundError`. It meets `tests/unit/.../blob/test_contract.py` beside the
GCS driver, so a test on it says what GCS would."""

from itertools import count
from typing import TYPE_CHECKING, ClassVar, Self

from e_infra.infra.errors import BlobNotFoundError, BlobPreconditionError
from e_infra.ports.blob import BlobMeta
from e_infra.ports.provider import Isolation, Locality, ProviderSpec, Workload

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class MemoryBlob:
    """Objects in a dict, generations from a counter."""

    spec: ClassVar[ProviderSpec] = ProviderSpec("memory-blob", Locality.EMBEDDED, Workload.IO_BOUND, Isolation.LOOP)

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, int]] = {}
        self._clock = count(1)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Nothing to release."""

    async def health(self) -> bool:
        return True

    async def put(self, key: str, data: bytes, *, if_generation: int | None = None) -> BlobMeta:
        held = self.objects.get(key, (b"", 0))[1]
        match if_generation:
            case int() as wanted if wanted != held:
                msg = f"{key}: generation {held}, the write expected {wanted}"
                raise BlobPreconditionError(msg)
        self.objects[key] = (bytes(data), next(self._clock))
        return BlobMeta(key=key, generation=self.objects[key][1], size=len(data))

    async def get(self, key: str) -> bytes:
        match self.objects.get(key):
            case None:
                raise BlobNotFoundError(key)
            case (data, _):
                return data

    async def head(self, key: str) -> BlobMeta | None:
        match self.objects.get(key):
            case None:
                return None
            case (data, generation):
                return BlobMeta(key=key, generation=generation, size=len(data))

    async def list(self, prefix: str) -> AsyncIterator[BlobMeta]:
        for key in sorted(name for name in self.objects if name.startswith(prefix)):
            data, generation = self.objects[key]
            yield BlobMeta(key=key, generation=generation, size=len(data))
