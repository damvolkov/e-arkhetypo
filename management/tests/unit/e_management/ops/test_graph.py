"""tests/unit/e_management/ops/graph: the graph algebra on synthetic DAGs — levels, closure, pinning and cycles, isolated from any filesystem."""

import pytest

from e_management.ops.deps import closure, levels, reverse
from e_management.ops.graph import forward, pinned, resolve


@pytest.fixture
def diamond():
    """a→{b,c}, b→d, c→d, d→∅ — the canonical diamond, one leaf, one apex."""
    files = {"a/x": ("src/a/x.py",), "b/y": ("src/b/y.py",), "c/z": ("src/c/z.py",), "d/w": ("src/d/w.py",)}
    imports = {
        "src/a/x.py": frozenset({"b/y", "c/z"}),
        "src/b/y.py": frozenset({"d/w"}),
        "src/c/z.py": frozenset({"d/w"}),
        "src/d/w.py": frozenset(),
    }
    return files, imports


def test_forward_drops_self_and_non_units(diamond) -> None:
    files, imports = diamond
    deps = forward(files, files, imports, frozenset())
    assert dict(deps) == {
        "a/x": frozenset({"b/y", "c/z"}),
        "b/y": frozenset({"d/w"}),
        "c/z": frozenset({"d/w"}),
        "d/w": frozenset(),
    }


def test_reverse_inverts_the_edge_set(diamond) -> None:
    files, imports = diamond
    back = reverse(forward(files, files, imports, frozenset()))
    assert back["d/w"] == frozenset({"b/y", "c/z"})
    assert back["a/x"] == frozenset()


def test_closure_is_transitive(diamond) -> None:
    files, imports = diamond
    deps = forward(files, files, imports, frozenset())
    assert closure(deps["a/x"], deps) == frozenset({"b/y", "c/z", "d/w"})  # what selecting a/x drags in
    assert closure(["a/x"], deps) == frozenset({"a/x", "b/y", "c/z", "d/w"})  # a seed set stays in its own closure


def test_levels_rank_leaves_at_zero(diamond) -> None:
    files, imports = diamond
    rank = levels(forward(files, files, imports, frozenset()))
    assert (rank["d/w"], rank["b/y"], rank["a/x"]) == (0, 1, 2)


def test_levels_raise_on_a_cycle() -> None:
    with pytest.raises(ValueError, match="cyclic"):
        levels({"a/x": frozenset({"b/y"}), "b/y": frozenset({"a/x"})})


def test_pinned_releases_a_detached_root_import() -> None:
    imports = {"src/app.py": frozenset({"b/y"}), "src/b/y.py": frozenset({"a/x"})}
    deps = {"b/y": frozenset({"a/x"}), "a/x": frozenset()}
    assert pinned(["src/app.py"], imports, deps, frozenset({"b/y"})) == frozenset()
    assert pinned(["src/app.py"], imports, deps, frozenset()) == frozenset({"b/y", "a/x"})


def test_resolve_sorts_by_key_and_locks(diamond) -> None:
    files, imports = diamond
    app_imports = {
        **imports,
        "src/app.py": frozenset({"a/x"}),
    }  # the service root reaches the apex, and so the whole diamond
    units = resolve(
        keys=files,
        files_of=files,
        tests_of={},
        package_of=dict.fromkeys(files, False),
        imports_map=app_imports,
        root_files=["src/app.py"],
        detach=frozenset(),
        skip=frozenset(),
    )
    assert [u.key for u in units] == sorted(files)
    assert all(u.locked for u in units)
