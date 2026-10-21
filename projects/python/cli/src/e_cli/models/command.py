"""models.command: the command tree as data — groups and cards the root reads before any command module loads."""

from dataclasses import dataclass


##### TYPES #####
@dataclass(frozen=True, slots=True)
class CommandGroup:
    """One node of the tree: `project env` nests under `project`; the empty parent is the root app itself."""

    path: str
    help: str

    @property
    def parent(self) -> str:
        return self.path.rpartition(" ")[0]

    @property
    def name(self) -> str:
        return self.path.rpartition(" ")[2]


@dataclass(frozen=True, slots=True)
class CommandCard:
    """One command: where it mounts, what implements it and what `--help` says of it.

    `target` is `module:function`, imported only when the command runs or its own help is asked for:
    `ecli --help` and every group listing are served from `summary`, never from the module."""

    path: str
    target: str
    summary: str

    @property
    def parent(self) -> str:
        return self.path.rpartition(" ")[0]

    @property
    def name(self) -> str:
        return self.path.rpartition(" ")[2]
