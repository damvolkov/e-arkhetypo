"""models.manifest: DTOs of the template registry (``data/templates.yml``) — validated at load, frozen forever after."""

from enum import StrEnum

from msgspec import Struct


##### TYPES #####
class Group(StrEnum):
    """What kind of decision a choice is: the UI orders its stages by this."""

    MODULES = "modules"
    STACK = "stack"
    CICD = "cicd"


class Strip(Struct, frozen=True, kw_only=True):
    """One guarded text rule: every whole-word ``frm`` becomes ``to``."""

    frm: str
    to: str


class Prune(Struct, frozen=True, kw_only=True):
    """Regex rewritten to ``to`` inside a project-relative file (multiline; empty ``to`` deletes)."""

    file: str
    pattern: str
    to: str = ""


class Detach(Struct, frozen=True, kw_only=True):
    """How the system lets go of one common unit: the paths it deletes and the texts it rewrites when dropped.

    A unit the system imports is pinned unless its detach rules erase every such import — the graph
    checks that on the live sources, so a rule that stops matching re-pins the unit instead of breaking the export."""

    unit: str
    paths: tuple[str, ...] = ()
    prunes: tuple[Prune, ...] = ()


class Common(Struct, frozen=True, kw_only=True):
    """The shared tree a system draws modules from: where it lives, its package, modules never exported, detachable units."""

    root: str
    package: str = "e_core"
    skip: tuple[str, ...] = ()
    detach: tuple[Detach, ...] = ()


class Material(Struct, frozen=True, kw_only=True):
    """A source tree or file materialized into the project, with the rules that strip its own package."""

    src: str
    dst: str
    strip: tuple[Strip, ...] = ()
    excludes: tuple[str, ...] = ()


class Choice(Struct, frozen=True, kw_only=True):
    """One toggleable slice of a system: what it removes, what it rewrites elsewhere, what it needs on.

    ``default`` is the pre-selection the UI starts from; a disabled choice contributes its
    ``paths`` and ``prunes`` to the plan."""

    name: str
    group: Group
    label: str = ""
    default: bool = True
    paths: tuple[str, ...] = ()
    prunes: tuple[Prune, ...] = ()
    requires: tuple[str, ...] = ()


class Verify(Struct, frozen=True, kw_only=True):
    """A post-export validation step: argv run in the new project; ``tests`` steps obey the user's choice."""

    name: str
    argv: tuple[str, ...] = ()
    tests: bool = False


class Template(Struct, frozen=True, kw_only=True):
    """One system ready to be copied, materialized, pruned, renamed and verified as a new project."""

    source: str
    package: str
    brand: str
    common: Common | None = None
    materials: tuple[Material, ...] = ()
    choices: tuple[Choice, ...] = ()
    mandatory: tuple[str, ...] = ()
    finalize: tuple[Prune, ...] = ()
    finalize_extra: tuple[Prune, ...] = ()
    drops: tuple[str, ...] = ()
    verify: tuple[Verify, ...] = ()


class Manifest(Struct, frozen=True, kw_only=True):
    """The whole registry: every template keyed by the name users pick."""

    templates: dict[str, Template]
