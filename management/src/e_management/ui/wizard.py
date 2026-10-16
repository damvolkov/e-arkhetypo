"""ui.wizard: the flow factory — the template, the CI library and the session become one walkable graph.

The wizard is the tui template's architecture applied to the house's real job: pages in order, one
*section* per decision. ``system`` picks the template (one of ``systems/``, never ``core`` — core is
the shared source), ``name`` names it, one ``tools-<area>`` page per discovered area of the common
tree (adapters, processors, …: import-traced units whose drop cascades over everything that imports
them), ``options`` toggles the template's own functional choices (stack, cicd, modules), ``ci``
toggles the CI features read from the library map — a feature whose ``requires`` is unselected makes
the plan raise at confirm, and the map keeps its promises honest — ``dest`` takes the destination and
``confirm`` forks the run. Every answer lands in ``FlowState.data`` under ``wizard.*``: the draft, the
plan preview and the generate step all read that one bag.

    graph = build_graph(manifest, "api", library=library, reference=reference, dep_graph=dep_graph, session=session)
"""

from collections.abc import Mapping
from typing import TYPE_CHECKING

from e_management.core.infra import Library
from e_management.core.session import Session
from e_tui.flow.page import Hook, Page
from e_tui.flow.pages import PagesBuilder
from e_tui.flow.state import seed
from e_tui.models.object import ChoiceSpec, Commit, ConfirmSpec, Field, InputSpec, ToggleSpec

if TYPE_CHECKING:
    from collections.abc import MutableMapping

    from e_management.core.infra import Library
    from e_management.models.graph import Graph as DepGraph
    from e_management.models.manifest import Manifest, Template
    from e_tui.flow.graph import Graph

##### KEYS #####
TEMPLATE = "wizard.template"
NAME = "wizard.name"
DEST = "wizard.dest"
OFF = "wizard.off"
DROP = "wizard.drop"
CI_OFF = "wizard.ci_off"


##### KEYS #####
# Textual ids forbid slashes: unit keys travel as hyphenated slugs and return to their dotted form in the hooks.


def slug(key: str) -> str:
    return key.replace("/", "-").replace(".", "-")


def unslug(key: str) -> str:
    return key.replace("-", "/")


##### HOOKS #####


def _record(key: str) -> Hook:
    """The simplest hook: park the committed answer under the dotted key of the shared state."""

    def hook(commit: Commit, state: MutableMapping[str, object]) -> None:
        seed(state, key, next(iter(commit.values), ""))

    return hook


def tools_hook(area: str, dep_graph: DepGraph) -> Hook:
    """Recompute the full drop set from this area's answer: other areas keep their drops, importers cascade."""

    def hook(commit: Commit, state: MutableMapping[str, object]) -> None:
        area_units = frozenset(unit.key for unit in dep_graph.in_area(area))
        previous = frozenset(_tuples(state.get(DROP)))
        kept = frozenset(unslug(v) for v in commit.values)
        off = (previous - area_units) | (area_units - kept)
        seed(state, DROP, tuple(sorted(dep_graph.cascade(off))))

    return hook


def options_hook(spec: Template) -> Hook:
    """The switched-off choice names, sorted — the plan re-validates every dependency between them."""

    def hook(commit: Commit, state: MutableMapping[str, object]) -> None:
        names = frozenset(choice.name for choice in spec.choices)
        seed(state, OFF, tuple(sorted(names - frozenset(commit.values))))

    return hook


def ci_hook(reference: tuple[str, ...]) -> Hook:
    """The feature names switched off from the project's CI reference; the map decides what they assemble."""

    def hook(commit: Commit, state: MutableMapping[str, object]) -> None:
        seed(state, CI_OFF, tuple(sorted(frozenset(reference) - frozenset(commit.values))))

    return hook


def _tuples(found: object) -> tuple[str, ...]:
    """Read a stored tuple back, never an auto-vivified ``State``."""
    return found if isinstance(found, tuple) else ()


def selection(data: Mapping[str, object]) -> tuple[frozenset[str], frozenset[str], frozenset[str], str, str, str]:
    """The accumulated answers read back as plan arguments: ``(off, drop, ci_off, template, name, dest)``."""
    return (
        frozenset(_tuples(_get_path(data, OFF))),
        frozenset(_tuples(_get_path(data, DROP))),
        frozenset(_tuples(_get_path(data, CI_OFF))),
        str(_get_path(data, TEMPLATE) or ""),
        str(_get_path(data, NAME) or ""),
        str(_get_path(data, DEST) or ""),
    )


def _get_path(state: Mapping[str, object], path: str) -> object:
    """Item access down a dotted path — nothing on this read path ever grows a node."""
    node: object = state
    for part in path.split("."):
        node = node.get(part) if isinstance(node, Mapping) else None
    return node


##### BUILDER #####


def build_graph(
    manifest: Manifest,
    template: str,
    *,
    library: Library | None = None,
    reference: tuple[str, ...] = (),
    dep_graph: DepGraph | None = None,
    session: Session | None = None,
) -> Graph:
    """Fold every section into one validated flow — the graph the wizard walks for this session."""
    spec = manifest.templates[template]
    carried = session or Session()
    off, drop, ci_off = frozenset(carried.off), frozenset(carried.drop), frozenset(carried.ci_off)
    builder = PagesBuilder("wizard")
    builder.add(
        Page(
            id="system",
            title="system",
            spec=ChoiceSpec(
                prompt="what kind of project? (core is the shared source, never a target)",
                fields=tuple(Field(key=name, label=f"systems/{name}") for name in sorted(manifest.templates)),
                selected=template,
            ),
            produces=frozenset({TEMPLATE}),
            on_commit=_record(TEMPLATE),
        )
    )
    builder.add(
        Page(
            id="name",
            title="name",
            spec=InputSpec(
                prompt="project name — lowercase, digits, underscores, starting with a letter", placeholder="myapp"
            ),
            requires=frozenset({TEMPLATE}),
            produces=frozenset({NAME}),
            on_commit=_record(NAME),
        )
    )
    if dep_graph is not None:
        for area in dep_graph.area_names():
            builder.add(_area_page(dep_graph, area, drop))
    if spec.choices:
        builder.add(
            Page(
                id="options",
                title="options",
                spec=ToggleSpec(
                    prompt="the service's own optional surfaces",
                    fields=tuple(
                        Field(key=choice.name, label=choice.name, detail=choice.label) for choice in spec.choices
                    ),
                    defaults=tuple(choice.name for choice in spec.choices if choice.name not in off),
                ),
                requires=frozenset({TEMPLATE}),
                produces=frozenset({OFF}),
                on_commit=options_hook(spec),
            )
        )
    if library is not None:
        builder.add(
            Page(
                id="ci",
                title="CI",
                spec=ToggleSpec(
                    prompt="CI features — the map decides which jobs each one assembles",
                    fields=tuple(_feature_fields(library)),
                    defaults=tuple(key for key in reference if key not in ci_off),
                    locked=("ci-basics",),
                ),
                requires=frozenset({TEMPLATE}),
                produces=frozenset({CI_OFF}),
                on_commit=ci_hook(reference),
            )
        )
    builder.add(
        Page(
            id="dest",
            title="dest",
            spec=InputSpec(prompt="destination folder — it must not exist yet", placeholder="../e-myapp"),
            requires=frozenset({NAME}),
            produces=frozenset({DEST}),
            on_commit=_record(DEST),
        )
    )
    builder.add(
        Page(
            id="confirm",
            title="confirm",
            spec=ConfirmSpec(
                prompt="generate? — the plan and the install checklist are shown before the engine runs",
                detail="verify after generate: git init · uv sync · make check",
            ),
            requires=frozenset({TEMPLATE, NAME, DEST}),
        )
    )
    return builder.build()


def _area_page(dep_graph: DepGraph, area: str, drop: frozenset[str]) -> Page:
    """One tools section: every unit of the area on its own switch, importers cascading out when it falls."""
    units = dep_graph.in_area(area)
    return Page(
        id=f"tools-{area}",
        title=area,
        spec=ToggleSpec(
            prompt=f"{area} — dropping a unit drops everything importing it",
            fields=tuple(
                Field(
                    key=slug(unit.key),
                    label=unit.key.rsplit("/", 1)[-1],
                    detail=_unit_detail(dep_graph, unit.key, drop),
                )
                for unit in units
            ),
            defaults=tuple(slug(unit.key) for unit in units if unit.key not in drop),
            locked=tuple(slug(unit.key) for unit in units if dep_graph.locked(unit.key, drop)),
        ),
        requires=frozenset({TEMPLATE}),
        produces=frozenset({DROP}),
        on_commit=tools_hook(area, dep_graph),
    )


def _unit_detail(dep_graph: DepGraph, key: str, drop: frozenset[str]) -> str:
    """The line the switch shows: who still needs this unit, or that nothing does."""
    needers = sorted(str(k).rsplit("/", 1)[-1] for k in dep_graph.needed_by(key, drop))
    return (
        f"needed by {', '.join(needers)}"
        if needers
        else "wired by the system"
        if key in dep_graph.required
        else "free to drop"
    )


def _feature_fields(library: Library) -> tuple[Field, ...]:
    """One field per library feature: its gate in the label, its requirements in the detail."""
    return tuple(
        Field(
            key=key,
            label=f"{key} → {spec.gate}" if spec.gate else key,
            detail=spec.label + (f" · requires {', '.join(spec.requires)}" if spec.requires else ""),
        )
        for key, spec in library.map.features.items()
    )
