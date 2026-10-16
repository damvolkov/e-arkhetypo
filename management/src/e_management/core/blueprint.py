"""core.blueprint: composition rules of a template for one target name — validate a selection, emit the ordered plan."""

import re
from typing import TYPE_CHECKING, cast

from e_management.core.errors import (
    ChoiceDependencyError,
    InvalidNameError,
    MandatoryCollisionError,
    UnknownChoiceError,
)
from e_management.core.infra import Library, assemble, derive
from e_management.core.plan import (
    Action,
    Copy,
    Generate,
    GeneratedFile,
    Materialize,
    Plan,
    PrunePaths,
    PruneTexts,
    Rename,
)
from e_management.models.manifest import Group, Strip

if TYPE_CHECKING:
    from e_management.models.graph import Graph
    from e_management.models.infra import Defaults
    from e_management.models.manifest import Choice, Template

##### DEFAULTS #####
SLUG: re.Pattern[str] = re.compile(r"^[a-z][a-z0-9_]*$")


##### TYPES #####
class Blueprint:
    """What a template becomes for a concrete name: package, brand, and a plan over a choice and unit selection."""

    __slots__ = ("_defaults", "_graph", "_library", "_spec", "name")

    def __init__(
        self,
        spec: Template,
        name: str,
        graph: Graph | None = None,
        library: Library | None = None,
        defaults: Defaults | None = None,
    ) -> None:
        if not SLUG.match(name):
            msg = f"{name!r} is not a slug: lowercase letters, digits, underscores, starting with a letter"
            raise InvalidNameError(msg)
        self._spec = spec
        self._graph = graph
        self._library = library
        self._defaults = defaults
        self.name = name

    ##### PRIVATE #####

    def _plan_check(self, off: frozenset[str]) -> None:
        declared = {choice.name for choice in self._spec.choices}
        if unknown := off - declared:
            msg = (
                f"unknown choice(s): {', '.join(sorted(unknown))}; declared: {', '.join(sorted(declared)) or '(none)'}"
            )
            raise UnknownChoiceError(msg)
        if broken := [
            (choice.name, sorted(set(choice.requires) & off))
            for choice in self._spec.choices
            if choice.name not in off and set(choice.requires) & off
        ]:
            msg = "; ".join(f"{name!r} requires {', '.join(missing)} switched off" for name, missing in broken)
            raise ChoiceDependencyError(msg)
        if clash := {path for choice in self._spec.choices for path in choice.paths} & set(self._spec.mandatory):
            msg = f"choices claim mandatory paths: {', '.join(sorted(clash))}"
            raise MandatoryCollisionError(msg)

    def _common_actions(self, drop: frozenset[str]) -> list[Action]:
        """The system's tree already carries the materialized common, so exporting only prunes what is unselected.

        Dropping a free unit removes it and its tests; the cascade removes everything importing it; a unit the
        service itself imports is refused by ``Graph.cascade`` unless its detach rules cut it out of the system —
        those rules run here too. Nothing is re-materialized, so the committed rewrite of the system stays authoritative."""
        graph = cast("Graph", self._graph)
        full = graph.cascade(drop)
        common = self._spec.common
        rules = [rule for rule in (common.detach if common else ()) if rule.unit in full]
        files = [
            *(path for key in sorted(full) for path in graph.unit(key).paths),
            *(p for r in rules for p in r.paths),
        ]
        prunes = tuple(prune for rule in rules for prune in rule.prunes)
        return [
            *([PrunePaths(paths=tuple(files))] if files else []),
            *([PruneTexts(prunes=prunes)] if prunes else []),
        ]

    def _infra_actions(self, off: frozenset[str], ci_off: frozenset[str]) -> list[Action]:
        """The CI files this project assembles: defaults minus the wizard's switches, tokens from the name and the reference."""
        if self._library is None or self._defaults is None:
            return []
        chosen = frozenset(self._defaults.features) - ci_off
        unknown = ci_off - set(self._defaults.features)
        if unknown:
            msg = f"unknown CI feature(s) switched off: {', '.join(sorted(unknown))}"
            raise ChoiceDependencyError(msg)
        on_choices = frozenset(
            f"{choice.group.value}.{choice.name}" for choice in self._spec.choices if choice.name not in off
        )
        gateable = frozenset(f"{choice.group.value}.{choice.name}" for choice in self._spec.choices)
        chosen_effective = frozenset(
            key for key in chosen if not (set(self._library.map.features[key].requires) & gateable) - on_choices
        )  # a feature gated on a switched-off choice (image on docker) leaves quietly — the map, not the user, decided.
        files = assemble(
            self._library, {**self._defaults.tokens, **derive(self.package, self.brand)}, chosen_effective, on_choices
        )
        return [Generate(files=tuple(GeneratedFile(path=key, content=body) for key, body in files.items()))]

    ############################################################

    ##### PUBLIC #####

    @property
    def package(self) -> str:
        return f"e_{self.name}"

    @property
    def brand(self) -> str:
        return f"e-{self.name}"

    @property
    def defaults_off(self) -> frozenset[str]:
        """The choice names a fresh session starts switched off."""
        return frozenset(choice.name for choice in self._spec.choices if not choice.default)

    def choices(self, group: Group | None = None) -> tuple[Choice, ...]:
        """The template's declared choices, optionally narrowed to one wizard group."""
        if group is None:
            return self._spec.choices
        return tuple(choice for choice in self._spec.choices if choice.group is group)

    def on(self, off: frozenset[str] = frozenset()) -> tuple[Choice, ...]:
        """Choices kept in the generated project — the selection after validation."""
        self._plan_check(off)
        return tuple(choice for choice in self._spec.choices if choice.name not in off)

    def plan(
        self,
        off: frozenset[str] = frozenset(),
        drop: frozenset[str] = frozenset(),
        ci_off: frozenset[str] = frozenset(),
    ) -> Plan:
        """The ordered actions: copy, prune dropped common, materialize dotfiles, prune choices, rename, finalize, assemble CI."""
        self._plan_check(off)
        actions: list[Action] = [Copy(src=self._spec.source, drops=self._spec.drops)]
        if self._graph is not None:
            actions += self._common_actions(drop)
        actions += [Materialize(src=m.src, dst=m.dst, strip=m.strip, excludes=m.excludes) for m in self._spec.materials]
        dropped = [choice for choice in self._spec.choices if choice.name in off]
        if paths := [path for choice in dropped for path in choice.paths]:
            actions.append(PrunePaths(paths=tuple(paths)))
        if prunes := [prune for choice in dropped for prune in choice.prunes]:
            actions.append(PruneTexts(prunes=tuple(prunes)))
        actions.append(
            Rename(rules=(Strip(frm=self._spec.package, to=self.package), Strip(frm=self._spec.brand, to=self.brand)))
        )
        finalize = self._spec.finalize + self._spec.finalize_extra
        if finalize:
            actions.append(PruneTexts(prunes=finalize))
        actions += self._infra_actions(off, ci_off)
        return Plan(name=self.name, package=self.package, brand=self.brand, actions=tuple(actions))
