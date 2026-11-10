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

from dataclasses import dataclass
from enum import Enum, auto
from functools import reduce
from typing import Final, Literal

from e_tui.flow.graph import Graph
from e_tui.flow.page import Page
from e_tui.infra.payload import JSON
from e_tui.infra.state import State

##### NAMESPACE #####
ANSWERS: Final = "answers"


##### SHADOW #####
class Marker(Enum):
    """Two one-of-a-kind values a path can hold in the shadow: produced (`PRESENCE`) or absent (`MISSING`)."""

    PRESENCE = auto()
    MISSING = auto()


PRESENCE: Final = Marker.PRESENCE
MISSING: Final = Marker.MISSING


@dataclass(slots=True, init=False)
class FlowState:
    """The one mutable truth of a walk: graph, position, trail, data."""

    graph: Graph
    at: str
    trail: tuple[str, ...]
    data: State

    def __init__(
        self, graph: Graph, at: str | None = None, trail: tuple[str, ...] = (), data: State | None = None
    ) -> None:
        """An unnamed position means the entry — one rule, applied once at birth."""
        self.graph = graph
        self.at = graph.entry.id if at is None else at
        self.trail = trail
        self.data = State() if data is None else data

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


def has(state: State, path: str) -> bool:
    """True when `path` already exists in `state` — the non-mutating presence test a `condition` must use."""
    head, _, rest = path.partition(".")
    match (state.get(head, MISSING), rest):
        case (Marker.MISSING, _):
            return False
        case (_, ""):
            return True
        case (State() as child, _):
            return has(child, rest)
        case _:
            return False


def _descend(node: State, key: str) -> State:
    """The child branch at `key`, grown on demand — reuses a `State`, never overwrites an existing branch."""
    match node.get(key):
        case State() as child:
            return child
        case _:
            grown = State()
            node[key] = grown
            return grown


def seed(state: State, path: str, value: JSON | Literal[Marker.PRESENCE]) -> None:
    """Set `path` to `value` inside `state`, materialising parent branches — how a shadow graph is built."""
    *parents, leaf = path.split(".")
    reduce(_descend, parents, state)[leaf] = value
