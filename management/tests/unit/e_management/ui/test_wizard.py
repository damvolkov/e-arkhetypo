"""tests/unit/e_management/ui/wizard: the flow factory in isolation — pages, hooks, slugs and the state the plan reads back."""

from pathlib import Path
from typing import TYPE_CHECKING

from e_management.cli import commands
from e_management.ui.wizard import build_graph, ci_hook, selection, slug, unslug
from e_tui.flow.graph import Graph  # noqa: TC001 — pages_of indexes it at runtime
from e_tui.flow.state import State, seed
from e_tui.models.object import Commit

if TYPE_CHECKING:
    from e_management.models.manifest import Manifest

MANIFEST = commands.registry(Path("data/templates.yml"))


def pages_of(graph: Graph) -> list[str]:
    return [page.id for page in graph.pages]


def test_a_bare_session_builds_the_fixed_sections() -> None:
    graph = build_graph(MANIFEST, "cli", library=None, reference=(), dep_graph=None)
    assert pages_of(graph) == ["system", "name", "dest", "confirm"]


def test_slugs_survive_the_round_trip() -> None:
    assert slug("adapters/md") == "adapters-md"
    assert unslug("adapters-md") == "adapters/md"
    assert slug("core.settings") == "core-settings"


def test_the_tools_hook_records_the_dropped_unit(repo: Path, spec: Manifest) -> None:
    dep = commands.dependency_map(repo, spec, "api")
    assert dep is not None
    page = build_graph(spec, "api", dep_graph=dep).page("tools-adapters")
    assert page.on_commit is not None
    state = State()
    kept = tuple(slug(unit.key) for unit in dep.in_area("adapters") if unit.key != "adapters/redis")
    page.on_commit(Commit(values=kept), state)
    assert "adapters/redis" in selection(state)[1]


def test_the_ci_hook_records_only_what_was_switched_off() -> None:
    state = State()
    ci_hook(("ci-basics", "docs", "pypi"))(Commit(values=("ci-basics", "pypi")), state)
    assert selection(state)[2] == frozenset({"docs"})


def test_selection_round_trips_the_state_bag() -> None:
    state = State()
    for key, value in {
        "wizard.template": "api",
        "wizard.name": "x",
        "wizard.dest": "/d",
        "wizard.off": ("docker",),
        "wizard.drop": ("adapters/redis",),
        "wizard.ci_off": ("docs",),
    }.items():
        seed(state, key, value)
    assert selection(state) == (
        frozenset({"docker"}),
        frozenset({"adapters/redis"}),
        frozenset({"docs"}),
        "api",
        "x",
        "/d",
    )
