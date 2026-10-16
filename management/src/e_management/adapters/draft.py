"""adapters.draft: persistence of the in-progress session — a timestamped, TTL'd envelope so a stale draft never hijacks a fresh start."""

import time
from typing import TYPE_CHECKING

import msgspec

from e_management.core.session import Session

if TYPE_CHECKING:
    from pathlib import Path

##### DEFAULTS #####
DEFAULT_TTL: float = 30 * 60  # a draft older than half an hour is abandoned, not resumed


##### TYPES #####
class Envelope(msgspec.Struct):
    """The on-disk shape: the session plus when it was written — the TTL is judged on the clock, not the file."""

    saved_at: float
    session: Session


class DraftStore:
    """One JSON file holding an ``Envelope``; ``load`` answers None when it is missing, corrupt, expired or schema-stale."""

    def __init__(self, path: Path, ttl: float = DEFAULT_TTL) -> None:
        self.path = path
        self.ttl = ttl

    def save(self, session: Session) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(msgspec.json.encode(Envelope(saved_at=time.time(), session=session)))

    def load(self) -> Session | None:
        envelope = self._read()
        if envelope is None or time.time() - envelope.saved_at > self.ttl:
            self.drop()
            return None
        return envelope.session

    def drop(self) -> None:
        self.path.unlink(missing_ok=True)

    ##### PRIVATE #####

    def _read(self) -> Envelope | None:
        if not self.path.exists():
            return None
        try:
            return msgspec.json.decode(self.path.read_bytes(), type=Envelope)
        except msgspec.DecodeError, OSError:
            return None
