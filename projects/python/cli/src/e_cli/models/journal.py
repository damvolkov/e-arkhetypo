"""models.journal: one recorded run — every key it wrote, with the value that key held before."""

from datetime import datetime

from msgspec import Struct


##### TYPES #####
class Journal(Struct, frozen=True, kw_only=True):
    """What undo needs to put the store back: `before` is None where the run created the key.

    `id` is the run's nanosecond clock, zero-padded, so journal keys sort in the order the runs happened."""

    id: str
    command: str
    at: datetime
    writes: tuple[tuple[str, bytes | None], ...]
