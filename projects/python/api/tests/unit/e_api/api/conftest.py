"""tests/unit/e_api/api: the sealed system walked whole, for the parity gate — every node of the real lifespan chain
with the path that places it."""

import dataclasses
from collections import defaultdict
from typing import TYPE_CHECKING, Final

import pytest

from e_api.infra.proxy import LazyProxy
from e_api.infra.state import State

### shared by nature, never a node held twice: interned atoms, and the lazy singletons `shared` mirrors on purpose.
ATOMS: Final[tuple[type, ...]] = (str, bytes, int, float, bool, type(None), LazyProxy)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from litestar.testing import TestClient

### the strata are every package of the service but its edge, `api`, where the lifespans and their sections live, and
### the common sections materialized beside it — tools, never a stratum's node.
SERVICE: Final[str] = "e_api."
EDGE: Final[tuple[str, ...]] = tuple(
    f"e_api.{name}." for name in ("api", "engines", "infra", "ops", "ports", "processors", "providers")
)


def leaves(node: object, chain: tuple[str, ...]) -> Iterator[tuple[str, str]]:
    """Every leaf under a node — `State` and typed sections walked alike — with the chain that places it: its own name
    one level under a stratum, its section's path deeper (`logic.agent`, `infra.providers`), and its class's module."""
    match node:
        case State():
            for name, child in node.items():
                yield from leaves(child, (*chain, name))
        case _ if dataclasses.is_dataclass(node):
            for each in dataclasses.fields(node):
                yield from leaves(getattr(node, each.name), (*chain, each.name))
        case _:
            yield (
                ".".join(chain if len(chain) <= 2 else chain[:-1]),
                type(getattr(node, "__wrapped__", node)).__module__,
            )


@pytest.fixture
def held(client: TestClient) -> list[tuple[str, str]]:
    """The sealed system's stratum nodes, after the real lifespan chain: each placing chain and its class's module."""
    return [
        (chain, module)
        for chain, module in leaves(client.app.state.system, ())
        if module.startswith(SERVICE) and not module.startswith(EDGE)
    ]


def held_at(node: object, chain: tuple[str, ...]) -> Iterator[tuple[str, object]]:
    """Every node under a node — sections and leaves alike — at its full dotted path."""
    match node:
        case State():
            for name, child in node.items():
                yield ".".join((*chain, name)), child
                yield from held_at(child, (*chain, name))
        case _ if dataclasses.is_dataclass(node):
            for each in dataclasses.fields(node):
                value = getattr(node, each.name)
                yield ".".join((*chain, each.name)), value
                yield from held_at(value, (*chain, each.name))


@pytest.fixture
def twins(client: TestClient) -> list[list[str]]:
    """Every object the sealed system holds at more than one path, by identity: the paths of each, sorted."""
    paths: defaultdict[int, list[str]] = defaultdict(list)
    _ = [
        paths[id(value)].append(path)
        for path, value in held_at(client.app.state.system, ())
        if not isinstance(value, ATOMS)
    ]
    return sorted(sorted(group) for group in paths.values() if len(group) > 1)
