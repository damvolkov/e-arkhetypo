"""adapters.stack: the port that persists the stack dependency map — build it from stack/, write the lock, read it back, diff for drift.

The model is derived by ``ops.stack`` from the tree; this store only moves it across the filesystem boundary and
detects when a committed ``stack.lock.yml`` no longer matches the services on disk.
"""

from typing import TYPE_CHECKING

import eserde

from e_management.models.stack import SCHEMA, Stack
from e_management.ops.stack import resolve

if TYPE_CHECKING:
    from pathlib import Path


##### TYPES #####
class StackStore:
    """Builds, writes, reads and diffs the stack dependency lock over a repository root."""

    __slots__ = ("root",)

    def __init__(self, root: Path) -> None:
        self.root = root

    ##### PRIVATE #####

    def _dir(self) -> Path:
        return self.root / "stack"

    ############################################################

    ##### PUBLIC #####

    def build(self) -> Stack:
        """The dependency map of every service under stack/, derived from its committed files."""
        return resolve(self._dir())

    def path(self) -> Path:
        """Where the lock lives — beside the services it describes."""
        return self._dir() / "stack.lock.yml"

    def dump(self, stack: Stack) -> bytes:
        """The canonical YAML bytes of a map: the exact body written or diffed."""
        return eserde.dumps(stack, format="yaml")

    def write(self) -> Path:
        """Derive and persist the lock; returns its path."""
        target = self.path()
        target.write_bytes(self.dump(self.build()))
        return target

    def read(self) -> Stack:
        """The committed lock, decoded back into the validated DTO."""
        return eserde.load(self.path(), type=Stack)

    def drift(self) -> list[str]:
        """Why the committed lock no longer matches the services — empty means in sync."""
        target = self.path()
        fresh = self.dump(self.build())
        match target.is_file():
            case False:
                return ["stack.lock.yml: missing"]
            case True if target.read_bytes() == fresh:
                return []
            case True if self._schema(target) != SCHEMA:
                return ["stack.lock.yml: stale schema, run make stack"]
            case True:
                return ["stack.lock.yml: drifted from stack/, run make stack"]

    def _schema(self, target: Path) -> int | None:
        try:
            return eserde.load(target, type=Stack).schema
        except eserde.LoaderError:
            return None
