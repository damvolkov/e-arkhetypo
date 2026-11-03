"""ports/watch: a folder watched for changes — batches of what was added, modified or deleted."""

from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from e_infra.ports.provider import Provider

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence
    from datetime import timedelta


class WatchChange(StrEnum):
    """What happened to a path."""

    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"


@runtime_checkable
class WatchPort(Provider, Protocol):
    """A folder's changes, gathered over `debounce` into one batch of `(change, path)`; an empty batch after `quiet`
    without events. `ignored` are name patterns (regular expressions) added to the provider's own; `polling` reads the
    folder on a clock instead of the OS's notifications."""

    def changes(
        self, folder: str, *, ignored: Sequence[str], debounce: timedelta, quiet: timedelta, polling: bool
    ) -> AsyncIterator[set[tuple[WatchChange, str]]]: ...
