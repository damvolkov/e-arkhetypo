"""tests/unit/e_management/adapters/graph: the store against the real api/cli systems — determinism, round-trip, classification and the committed lock."""

import eserde
import pytest

from e_management.adapters.graph import GraphStore
from e_management.models.graph import Graph


@pytest.fixture
def api_graph(repo, spec) -> Graph:
    return GraphStore(repo).build(spec.templates["api"], "api")


def test_graph_build_is_deterministic(repo, spec) -> None:
    built = GraphStore(repo)
    first = built.dump(built.build(spec.templates["api"], "api"))
    assert first == built.dump(built.build(spec.templates["api"], "api"))


def test_graph_round_trips_through_yaml(repo, spec, api_graph) -> None:
    raw = GraphStore(repo).dump(api_graph)
    assert eserde.loads(raw, type=Graph, format="yaml") == api_graph


def test_graph_locks_exactly_what_the_service_pins(api_graph) -> None:
    units = {u.key: u for u in api_graph.units}
    assert units["adapters/sqlite"].locked
    assert not units["adapters/sqlite"].detachable
    assert units["adapters/http"].detachable
    assert not units["adapters/http"].locked
    assert units["adapters/ports"].locked  # imported directly by the app


def test_graph_closure_is_the_recursive_traceability(api_graph) -> None:
    units = {u.key: u for u in api_graph.units}
    assert {"adapters/base", "core/settings", "core/proxy", "ops/file"} <= set(units["adapters/http"].closure)


def test_graph_levels_are_topological(api_graph) -> None:
    units = {u.key: u for u in api_graph.units}
    assert all(units[dep].level < unit.level for unit in api_graph.units for dep in unit.deps)


def test_committed_locks_are_in_sync(repo, spec) -> None:
    built = GraphStore(repo)
    assert built.drift(spec.templates["api"], "api") == []
    assert built.drift(spec.templates["cli"], "cli") == []


def test_cli_locks_only_what_its_root_reaches(repo, spec) -> None:
    cli = GraphStore(repo).build(spec.templates["cli"], "cli")
    units = {u.key: u for u in cli.units}
    assert units["adapters/sqlite"].locked
    assert not units["adapters/http"].locked
    assert not units["core/crypto"].locked  # the demo service never reaches crypto
    assert not any(u.detachable for u in cli.units)  # the cli declares no detach rules at all
