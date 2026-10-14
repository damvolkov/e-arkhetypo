"""models.graph: the resolved dependency graph as a persisted DTO and the queries the exporter runs on it.

The shape is canonical by construction: every collection is a ``tuple`` the resolver hands over already sorted, and
``eserde`` emits ``Struct`` fields in declaration order, so the same sources serialize to the same bytes. ``schema``
guards the derivation logic; ``inputs_hash`` guards the sources feeding it. The query methods are the exported
contract: what a unit drags in, what would go if it dropped, and what the system pins — pure views over the units.
"""

from msgspec import Struct

SCHEMA = 1


##### TYPES #####
class Unit(Struct, frozen=True, kw_only=True):
    """One exportable node of the common tree: a module or package, what it depends on and what it drags along."""

    key: str
    area: str
    name: str
    files: tuple[str, ...]
    package: bool = False
    tests: tuple[str, ...] = ()
    deps: tuple[str, ...] = ()
    dependents: tuple[str, ...] = ()
    closure: tuple[str, ...] = ()
    level: int = 0
    locked: bool = False
    detachable: bool = False

    @property
    def paths(self) -> tuple[str, ...]:
        """Every project path the unit owns — its sources plus the tests that materialize with it."""
        return (*self.files, *self.tests)


class Graph(Struct, frozen=True, kw_only=True):
    """The whole dependency graph of one system, derived from its sources and ready to be committed."""

    schema: int
    system: str
    package: str
    source: str
    areas: tuple[str, ...]
    inputs_hash: str
    units: tuple[Unit, ...]

    ##### QUERIES #####

    def area_names(self) -> tuple[str, ...]:
        return self.areas

    def in_area(self, area: str) -> tuple[Unit, ...]:
        return tuple(unit for unit in self.units if unit.area == area)

    def unit(self, key: str) -> Unit:
        return next(unit for unit in self.units if unit.key == key)

    @property
    def required(self) -> frozenset[str]:
        """The units the service pins, directly or transitively — dropping any of them breaks the system."""
        return frozenset(unit.key for unit in self.units if unit.locked)

    def needed_by(self, key: str, drop: frozenset[str]) -> frozenset[str]:
        """The units still kept that import ``key``: while any remains, ``key`` goes with them."""
        return frozenset(self.unit(key).dependents) - drop

    def requires(self, key: str) -> frozenset[str]:
        """Everything ``key`` imports, transitively: switching ``key`` on brings all of it back."""
        return frozenset(self.unit(key).closure)

    def locked(self, key: str, drop: frozenset[str]) -> bool:
        """Not the user's call: the system pins it, or a unit that stays imports it."""
        return key in self.required or bool(self.needed_by(key, drop))

    def cascade(self, drop: frozenset[str]) -> frozenset[str]:
        """The full drop set after cascading to every importer of a dropped unit; raises when a required unit would fall."""
        importers = {unit.key: frozenset(unit.dependents) for unit in self.units}
        full, stack = set(drop), list(drop)
        while stack:
            full.update(fresh := importers.get(stack.pop(), frozenset()) - full)
            stack.extend(fresh)
        if pinned := full & self.required:
            msg = f"the system itself imports {', '.join(sorted(pinned))} — it cannot be dropped"
            raise ValueError(msg)
        return frozenset(full)
