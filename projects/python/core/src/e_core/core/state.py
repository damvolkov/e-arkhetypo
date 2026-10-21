"""core/state: the app resource graph — dynamic attribute access all the way down.

Shape is created by referencing it: `state.adapters.store = SQLiteAdapter()`, even
`state.buses.events.sinks = []` from zero — reading an unset node auto-vivifies an empty child
`State` that stays in the tree. After `seal()` (the lifespan chain's last act) the graph is
strict: no writes anywhere, and a typo on read raises instead of silently growing a node. The
seal freezes the graph's shape; each leaf (stores, engines, lists) keeps its ordinary Python life.

A `State` is also a full `MutableMapping` — dict-compatible wherever a host framework (litestar)
expects one. Attribute names that collide with mapping methods (`keys`, `items`) are read via
`state["keys"]`."""

from collections.abc import Iterator, MutableMapping
from typing import Any


##### TYPES #####
class State(MutableMapping[str, object]):
    """A node of the graph: attribute- and item-access to a dict that deepens on demand while open.

    The attribute surface (`__getattr__`) stays dynamic `Any` — auto-vivification is its contract;
    the mapping surface yields `object`, and consumers cast or narrow at the use site."""

    __slots__ = ("_nodes", "_sealed")

    def __init__(self, **nodes: object) -> None:
        object.__setattr__(self, "_nodes", dict(nodes))
        object.__setattr__(self, "_sealed", False)

    ##### MAPPING CORE #####
    def __getitem__(self, name: str) -> object:
        return self._nodes[name]

    def __setitem__(self, name: str, value: object) -> None:
        self._check_writable()
        self._nodes[name] = value

    def __delitem__(self, name: str) -> None:
        self._check_writable()
        del self._nodes[name]

    def __iter__(self) -> Iterator[str]:
        return iter(self._nodes)

    def __len__(self) -> int:
        return len(self._nodes)

    ##### ATTRIBUTE SURFACE #####
    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        try:
            return self._nodes[name]
        except KeyError:
            match self._sealed:
                case True:
                    msg = f"Sealed state has no node {name!r}: {sorted(self._nodes)}"
                    raise AttributeError(msg) from None
                case _:
                    child = self._nodes[name] = State()
                    return child

    def __setattr__(self, name: str, value: object) -> None:
        self._check_writable()
        self._nodes[name] = value

    def __delattr__(self, name: str) -> None:
        self._check_writable()
        self._nodes.pop(name, None)

    def __repr__(self) -> str:
        return f"State({', '.join(sorted(self._nodes))})"

    ##### LIFECYCLE #####
    def copy(self) -> State:
        """Shallow snapshot: same nodes and leaves, independent dict — what a host framework may expect."""
        clone = State(**self._nodes)
        object.__setattr__(clone, "_sealed", self._sealed)
        return clone

    def seal(self) -> None:
        """Close the whole subtree: from now on, reads of declared nodes only."""
        object.__setattr__(self, "_sealed", True)
        for child in self._nodes.values():
            match child:
                case State():
                    child.seal()

    def _check_writable(self) -> None:
        match self._sealed:
            case True:
                msg = "Sealed state: the graph is built at startup, mutated never"
                raise RuntimeError(msg)
            case _:
                pass
