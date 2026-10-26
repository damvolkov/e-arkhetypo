"""e_tui.flow.state: the shared bag a walk carries — progress, trail for the reverse, domain data.

One `State` (the dynamic, auto-vivifying graph of resources from infra) holds everything the walk touches:
under ``answers``, the values committed per page (the reverse re-shows them, the routes read them); under any
other branch, whatever domain models the host app parks there — the template never reaches past the namespace
it owns. Progress is two plain values: where we are and the trail walked to get here. A `FlowState` is mutable
by nature — the walk *is* change.

The path helpers `has` and `seed` exist because `State` auto-vivifies on *attribute* access: `state.system`
silently grows an empty node and reads as present forever, so a placement check written against attributes
never fails. Presence is therefore tested by item access (`.get`, no mutation) and the shadow graph the
validator builds is seeded by item assignment. Dotted paths (`system.template`) descend and grow as needed."""

from collections.abc import MutableMapping
from dataclasses import dataclass, field
from functools import reduce
from typing import Final

from e_tui.flow.graph import Graph
from e_tui.flow.page import Page
from infra.state import State

##### NAMESPACE #####
ANSWERS: str = "answers"

##### SHADOW #####
MISSING: Final[object] = object()  # the "no such path" marker — a real value is never this


@dataclass(slots=True)
class FlowState:
    """The one mutable truth of a walk: graph, position, trail, data."""

    graph: Graph
    at: str = ""
    trail: tuple[str, ...] = ()
    data: State = field(default_factory=State)

    def __post_init__(self) -> None:
        """An unnamed position means the entry — one rule, applied once at birth."""
        self.at = self.at or self.graph.entry.id

    ##### VIEWS #####

    @property
    def here(self) -> Page:
        """The page under the cursor."""
        return self.graph.page(self.at)

    @property
    def answers(self) -> State:
        """page id → committed values, created inside the data bag on first use."""
        return getattr(self.data, ANSWERS)

    def values_for(self, step: str) -> tuple[str, ...]:
        """What `step` already committed — empty the first time, restored after a reverse."""
        stored = self.answers.get(step, ())
        return stored if isinstance(stored, tuple) else ()


##### PATHS #####


def _child(node: object, key: str) -> object:
    """The value under `key` in a mapping, or `MISSING` — item access, so nothing auto-vivifies."""
    match node:
        case MutableMapping() as mapping:
            return mapping.get(key, MISSING)
        case _:
            return MISSING


def has(state: object, path: str) -> bool:
    """True when `path` already exists in `state` — the non-mutating presence test a `condition` must use."""
    return reduce(_child, path.split("."), state) is not MISSING


def _descend(node: MutableMapping[str, object], key: str) -> MutableMapping[str, object]:
    """The child branch at `key`, grown on demand — reuses a `State`, never overwrites an existing branch."""
    match node.get(key):
        case State() as child:
            return child
        case _:
            grown = State()
            node[key] = grown
            return grown


def seed(state: MutableMapping[str, object], path: str, value: object) -> None:
    """Set `path` to `value` inside `state`, materialising parent branches — how a shadow graph is built."""
    *parents, leaf = path.split(".")
    reduce(_descend, parents, state)[leaf] = value
