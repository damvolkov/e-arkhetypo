"""ports/shapes: a SHACL engine — data and shapes in, a report out; `conforms is None` means «not validated».

Stateless: every call carries its data (a release's graphs and the candidate) and its shapes. An engine that cannot run
a constraint it was given says so in `skipped` and answers `None`: a gate reads `None` as a block, never as a pass.
Engines are compared by `Violation.key` — the shape's local name, or `Component@path` for a blank property shape — so
two engines agree on what fired whatever they name a blank node."""

from typing import Protocol, runtime_checkable

import msgspec

from e_infra.ports.provider import Provider
from e_infra.ports.triples import Serialization


def _local(iri: str) -> str:
    return iri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


class Violation(msgspec.Struct, frozen=True, kw_only=True):
    """One broken constraint: the node it fell on, the shape's message, the shape, its component, the path."""

    focus_node: str
    message: str = ""
    source_shape: str = ""
    component: str = ""
    path: str = ""

    @property
    def key(self) -> str:
        """What fired, engine-neutral."""
        named = self.source_shape.startswith(("http://", "https://", "urn:"))
        return _local(self.source_shape) if named else f"{_local(self.component)}@{_local(self.path)}"


class Report(msgspec.Struct, frozen=True, kw_only=True):
    """The verdict: True, False, or None when the engine skipped what it could not run (named in `skipped`)."""

    conforms: bool | None
    violations: tuple[Violation, ...] = ()
    skipped: tuple[str, ...] = ()

    @property
    def keys(self) -> frozenset[str]:
        """Every constraint that fired, by key."""
        return frozenset(each.key for each in self.violations)


@runtime_checkable
class ShapesPort(Provider, Protocol):
    """Data that does not parse is a `ShapesError`."""

    async def validate(
        self, data: bytes, shapes: bytes, serialization: Serialization = Serialization.TURTLE
    ) -> Report: ...
