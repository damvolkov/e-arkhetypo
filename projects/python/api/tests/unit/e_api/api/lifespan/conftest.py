"""tests/unit/e_api/api/lifespan: what the lifespans log, recorded — structlog caches its bound logger on first use, so
a capture installed later never sees it; the lifespan module's `logger` is swapped for a recorder instead. And the
sealed system walked whole, for the parity gate."""

import dataclasses
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

import pytest

from e_api.api.lifespan import adapters
from infra.proxy import LazyProxy
from infra.state import State

### shared by nature, never a node held twice: interned atoms, and the lazy singletons `shared` mirrors on purpose.
ATOMS: Final[tuple[type, ...]] = (str, bytes, int, float, bool, type(None), LazyProxy)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from litestar.testing import TestClient

### the strata are every package of the service but its edge, `api`, where the lifespans and their sections live.
SERVICE: Final[str] = "e_api."
EDGE: Final[str] = "e_api.api."


@dataclass(slots=True)
class LogRecorder:
    """Every event logged through it: its level, its name, its fields."""

    events: list[tuple[str, str, dict[str, object]]] = field(default_factory=list)

    def info(self, event: str, **fields: object) -> None:
        self.events.append(("info", event, fields))

    def warning(self, event: str, **fields: object) -> None:
        self.events.append(("warning", event, fields))


@pytest.fixture
def logs(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, dict[str, object]]]:
    """The adapters lifespan's events as they are logged — level, name, fields."""
    recorder = LogRecorder()
    monkeypatch.setattr(adapters, "logger", recorder)
    return recorder.events


def leaves(node: object, chain: tuple[str, ...]) -> Iterator[tuple[str, str]]:
    """Every leaf under a node — `State` and typed sections walked alike — with the chain that places it: its own name
    one level under a stratum, its section's path deeper (`logic.agent`, `infra.adapters`), and its class's module."""
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
