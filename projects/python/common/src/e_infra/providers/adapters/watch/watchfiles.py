"""providers/adapters/watch/watchfiles: a folder's changes on watchfiles (Rust `notify`), the `WatchPort`.

Its default ignore patterns (VCS folders, editor swaps, caches) stay on; the caller's are added. One watcher per call:
a stream of batches, yielded on a quiet tick too, each reaching the caller before the next is read."""

from types import MappingProxyType
from typing import TYPE_CHECKING, ClassVar, Final, Self

from watchfiles import Change, DefaultFilter, awatch

from e_infra.infra.logger import logger
from e_infra.ports.provider import Isolation, Locality, ProviderSpec, Workload
from e_infra.ports.watch import WatchChange

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Sequence
    from datetime import timedelta

MS: Final[int] = 1_000
CHANGES: Final[MappingProxyType[Change, WatchChange]] = MappingProxyType(
    {Change.added: WatchChange.ADDED, Change.modified: WatchChange.MODIFIED, Change.deleted: WatchChange.DELETED}
)


##### ADAPTER #####
class WatchfilesAdapter:
    """One folder watcher per call: a stream of batches, yielded on a quiet tick too."""

    spec: ClassVar[ProviderSpec] = ProviderSpec("watchfiles", Locality.EMBEDDED, Workload.IO_BOUND, Isolation.THREAD)

    __slots__ = ()

    ##### PUBLIC #####

    async def __aenter__(self) -> Self:
        logger.info("watchfiles opened")
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Each watcher lives in its call: nothing held here."""
        logger.info("watchfiles closed")

    async def health(self) -> bool:
        """In process, nothing held: it answers."""
        return True

    async def changes(
        self, folder: str, *, ignored: Sequence[str], debounce: timedelta, quiet: timedelta, polling: bool
    ) -> AsyncGenerator[set[tuple[WatchChange, str]]]:
        """The folder's batches until cancelled; a batch with no event after `quiet`."""
        logger.debug("watchfiles watch", folder=folder, polling=polling)
        events = awatch(
            folder,
            watch_filter=DefaultFilter(ignore_entity_patterns=(*DefaultFilter.ignore_entity_patterns, *ignored)),
            debounce=int(debounce.total_seconds() * MS),
            rust_timeout=int(quiet.total_seconds() * MS),
            yield_on_timeout=True,
            force_polling=polling,
        )
        ### an async stream is relayed as it comes: each batch reaches the caller before the next is read.
        async for batch in events:
            yield {(CHANGES[change], path) for change, path in batch}
