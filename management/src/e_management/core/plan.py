"""core.plan: the generation as data — an ordered list of actions, nothing executed, everything inspectable."""

from msgspec import Struct

from e_management.models.manifest import Prune, Strip


##### TYPES #####
class Copy(Struct, frozen=True, kw_only=True):
    """The template tree, verbatim, minus skips and drops."""

    src: str
    drops: tuple[str, ...] = ()


class Materialize(Struct, frozen=True, kw_only=True):
    """A shared asset copied over its destination, stripped of its own package paths."""

    src: str
    dst: str
    strip: tuple[Strip, ...] = ()
    excludes: tuple[str, ...] = ()


class PrunePaths(Struct, frozen=True, kw_only=True):
    """Paths removed from the generated tree (files or whole directories)."""

    paths: tuple[str, ...] = ()


class PruneTexts(Struct, frozen=True, kw_only=True):
    """Regex deletions applied to files inside the generated tree."""

    prunes: tuple[Prune, ...] = ()


class Rename(Struct, frozen=True, kw_only=True):
    """Whole-word renames over every text file and every path segment of the tree."""

    rules: tuple[Strip, ...] = ()


class GeneratedFile(Struct, frozen=True, kw_only=True):
    """One file the CI assembler produced: where it lands and the exact bytes it holds."""

    path: str
    content: str


class Generate(Struct, frozen=True, kw_only=True):
    """Files materialized from the infra library — assembled under the final name, applied last, never renamed."""

    files: tuple[GeneratedFile, ...] = ()


Action = Copy | Materialize | PrunePaths | PruneTexts | Rename | Generate


class Plan(Struct, frozen=True, kw_only=True):
    """A complete, ordered recipe for one project."""

    name: str
    package: str
    brand: str
    actions: tuple[Action, ...] = ()
