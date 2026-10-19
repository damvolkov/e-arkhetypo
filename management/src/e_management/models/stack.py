"""models.stack: the flat map of the stack/ services — every compose as a node, its sidecars, and the dependency edges resolved from host references.

A node is the *global service name* (``vllm``, ``openwebui``), the identity Docker resolves over the shared network;
the category is metadata (``llm``, ``front``) — the parent directory. The query methods are the contract the
management tool runs on: selecting a service answers its full dependency closure, and the level orders a merge so
dependencies come before dependents. Deterministic by construction, exactly like ``models.graph``.
"""

from msgspec import Struct

SCHEMA = 1


##### TYPES #####
class Service(Struct, frozen=True, kw_only=True):
    """One stack service: where it lives, what it needs, and what hangs off it."""

    name: str
    category: str
    compose: str | None = None
    files: tuple[str, ...]
    port: int | None = None
    depends: tuple[str, ...] = ()
    dependents: tuple[str, ...] = ()
    closure: tuple[str, ...] = ()
    level: int = 0

    @property
    def paths(self) -> tuple[str, ...]:
        """Every file the service ships: its compose, when it has one, plus the config/entrypoint/provisioning sidecars."""
        return (*((self.compose,) if self.compose else ()), *self.files)


class Stack(Struct, frozen=True, kw_only=True):
    """The whole stack dependency map, derived from stack/ and ready to be committed as stack.lock.yml."""

    schema: int
    root: str
    categories: tuple[str, ...]
    inputs_hash: str
    services: tuple[Service, ...]

    ##### QUERIES #####

    def names(self, category: str | None = None) -> tuple[str, ...]:
        return tuple(s.name for s in self.services if category is None or s.category == category)

    def service(self, name: str) -> Service:
        return next(s for s in self.services if s.name == name)

    def requires(self, name: str) -> frozenset[str]:
        """Everything ``name`` transitively depends on — what it pulls in when chosen: the resolved closure, stored per service."""
        return frozenset(self.service(name).closure)

    def needed_by(self, name: str, chosen: frozenset[str]) -> frozenset[str]:
        """The chosen services that would break if ``name`` were dropped: its chosen dependents."""
        return frozenset({s.name for s in self.services if name in s.depends}) & chosen

    def select(self, chosen: frozenset[str]) -> tuple[str, ...]:
        """The flat merge list: every chosen service plus, transitively, everything it depends on, ordered so a dependency precedes its dependents."""
        wanted = {name for c in chosen for name in self.requires(c)}
        ranked = {s.name: s.level for s in self.services}
        return tuple(sorted(wanted, key=lambda name: (ranked[name], name)))

    def orphans(self, chosen: frozenset[str]) -> frozenset[str]:
        """Chosen services whose dependencies are not themselves chosen — the raw selection before closure, for reporting."""
        return frozenset({name for c in chosen for name in self.service(c).depends if name not in chosen})
