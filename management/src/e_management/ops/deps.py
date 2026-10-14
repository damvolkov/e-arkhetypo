"""ops.deps: the key-agnostic graph algebra — reverse edges, forward closure, topological levels and the drift digest.

Nothing here knows what a node is (a module unit, a stack service): it only speaks ``node -> set(node)`` adjacency.
Both ``ops.graph`` (systems) and ``ops.stack`` (stack services) build their model on these primitives, so the one
hard part — transitive closure and level assignment over a possibly deep graph — is written and tested once.
"""

import hashlib
from collections import deque
from functools import reduce
from graphlib import CycleError, TopologicalSorter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Mapping


def reverse(deps: Mapping[str, frozenset[str]]) -> dict[str, frozenset[str]]:
    """For each node, the importers that name it — the direction that answers whether it can be dropped."""
    return {key: frozenset(importer for importer, targets in deps.items() if key in targets) for key in deps}


def closure(seeds: Collection[str], deps: Mapping[str, frozenset[str]]) -> frozenset[str]:
    """Everything reachable forward from seeds — an explicit frontier, since a graph has no bounded depth."""
    empty: frozenset[str] = frozenset()
    reached, frontier = set(seeds), deque(seeds)
    while frontier:
        reached.update(unseen := deps.get(frontier.popleft(), empty).difference(reached))
        frontier.extend(unseen)
    return frozenset(reached)


def _rank(rank: dict[str, int], deps: Mapping[str, frozenset[str]], key: str) -> dict[str, int]:
    return rank | {key: 1 + max((rank[dep] for dep in deps[key]), default=-1)}


def order(deps: Mapping[str, frozenset[str]]) -> tuple[str, ...]:
    """A topological order, dependencies first; raises ValueError when the graph is cyclic."""
    try:
        return tuple(TopologicalSorter(deps).static_order())
    except CycleError as exc:
        msg = f"the dependency graph is cyclic: {exc.args[1]}"
        raise ValueError(msg) from exc


def levels(deps: Mapping[str, frozenset[str]]) -> dict[str, int]:
    """Longest-path rank per node: 0 for a leaf, one above its deepest dependency."""
    return reduce(lambda rank, key: _rank(rank, deps, key), order(deps), {})


def digest(sources: Mapping[str, bytes], rules: Iterable[str]) -> str:
    """A content hash over every parsed source and the rules that shaped the model — the drift sentinel."""
    blob = b"".join(f"{path}\0".encode() + content + b"\n" for path, content in sorted(sources.items()))
    return hashlib.sha256(blob + "\0".join(sorted(rules)).encode()).hexdigest()
