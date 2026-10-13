"""runtime.journal: undo for free — a StorePort decorator that records what every write overwrote.

A command writes through `StoreJournal` believing it is the store. The first write to each key records
the value it held; on a clean exit the run is filed as one `Journal` entry, on an exception nothing is
filed. `undo` puts the newest entry's keys back and forgets it. No command writes inverse logic: being
revertible is a property of writing through the port."""

import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import TracebackType
from typing import ClassVar, Self

import msgspec

from adapters.ports import StorePort
from e_cli.models.error import JournalError
from e_cli.models.journal import Journal

##### DEFAULTS #####
PREFIX: str = "journal:"


##### TYPES #####
class StoreJournal:
    """Satisfies StorePort; reads pass through, writes are recorded, the run commits on a clean `__aexit__`."""

    name: ClassVar[str] = "journal"

    __slots__ = ("_command", "_depth", "_inner", "_writes")

    def __init__(self, inner: StorePort, command: str, depth: int) -> None:
        self._inner = inner
        self._command = command
        self._depth = depth
        self._writes: dict[str, bytes | None] = {}

    ##### PRIVATE METHODS #####

    async def _common_record(self, key: str) -> None:
        """Keep the value from before the run: a key written twice restores to its first state."""
        match key in self._writes:
            case False:
                self._writes[key] = await self._inner.get(key)
            case _:
                pass

    async def _commit_file(self) -> None:
        entry = Journal(
            id=f"{time.time_ns():020d}",
            command=self._command,
            at=datetime.now(UTC),
            writes=tuple(self._writes.items()),
        )
        await self._inner.set(f"{PREFIX}{entry.id}", msgspec.json.encode(entry))
        for stale in (await self._common_ids())[: -self._depth]:
            await self._inner.delete(f"{PREFIX}{stale}")

    async def _common_ids(self) -> list[str]:
        """Entry ids, oldest first: the zero-padded clock makes lexical order the order of the runs."""
        return sorted([key.removeprefix(PREFIX) async for key in self._inner.keys(PREFIX)])

    ############################################################

    ##### PUBLIC #####

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        ### a failed run changed the store partially at most: filing it would make undo restore a half-state.
        match (exc_type, bool(self._writes)):
            case (None, True):
                await self._commit_file()
            case _:
                pass

    async def get(self, key: str) -> bytes | None:
        return await self._inner.get(key)

    async def set(self, key: str, value: bytes) -> None:
        await self._common_record(key)
        await self._inner.set(key, value)

    async def delete(self, key: str) -> None:
        await self._common_record(key)
        await self._inner.delete(key)

    def keys(self, prefix: str = "") -> AsyncIterator[str]:
        return self._inner.keys(prefix)

    async def entries(self) -> list[Journal]:
        """Every filed run, newest first."""
        ids = await self._common_ids()
        return [
            msgspec.json.decode(raw, type=Journal)
            for entry_id in reversed(ids)
            if (raw := await self._inner.get(f"{PREFIX}{entry_id}")) is not None
        ]

    async def undo(self) -> Journal:
        """Restore every key of the newest run to its prior value, then forget the run. Undo is not journaled."""
        match next(iter(await self.entries()), None):
            case None:
                msg = "nothing to undo: the journal is empty"
                raise JournalError(msg)
            case last:
                for key, before in last.writes:
                    await (self._inner.delete(key) if before is None else self._inner.set(key, before))
                await self._inner.delete(f"{PREFIX}{last.id}")
                return last
