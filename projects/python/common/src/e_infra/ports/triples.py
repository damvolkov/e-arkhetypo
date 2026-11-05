"""ports/triples: a triple store by named graph — SPARQL 1.1 Query and Update, graphs loaded and dumped whole.

A query's default graph is the union of every named graph: an answer spans core, app and instance unless the query
names a `GRAPH`. Parameters reach a query as typed terms (`substitutions`), bound into the compiled query, never spliced
into its text. Answers stream: `select` is iterated, never collected by the store. Values come back as their lexical
form — an IRI as itself, a literal as its value, a blank node as `_:id`. A caller that stops early closes the stream
(`aclose`, `contextlib.aclosing`): the store frees the answer then, not when it is collected."""

from enum import StrEnum, auto
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import msgspec

from e_infra.ports.provider import Provider

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Mapping

type Binding = dict[str, str]


class Serialization(StrEnum):
    """An RDF syntax a graph travels in."""

    TURTLE = auto()
    NTRIPLES = auto()
    NQUADS = auto()
    TRIG = auto()
    JSONLD = auto()
    RDFXML = auto()


class TermKind(StrEnum):
    IRI = auto()
    LITERAL = auto()


class Term(msgspec.Struct, frozen=True, kw_only=True):
    """A value a query is called with: an IRI, or a literal with its datatype or language."""

    value: str
    kind: TermKind = TermKind.LITERAL
    datatype: str | None = None
    language: str | None = None


@runtime_checkable
class TriplesPort(Provider, Protocol):
    """`load` adds to a graph and answers its size; `graphs` counts each named graph; `convert` reads one syntax into
    another without touching the store; refusals are `TriplesError`."""

    async def load(self, graph: str, data: bytes, serialization: Serialization) -> int: ...

    async def convert(self, data: bytes, source: Serialization, target: Serialization) -> bytes: ...

    async def dump(self, graph: str, serialization: Serialization = Serialization.NTRIPLES) -> bytes: ...

    async def clear(self, graph: str) -> None: ...

    async def graphs(self) -> dict[str, int]: ...

    def select(self, sparql: str, substitutions: Mapping[str, Term] | None = None) -> AsyncGenerator[Binding]: ...

    async def ask(self, sparql: str, substitutions: Mapping[str, Term] | None = None) -> bool: ...

    async def update(self, sparql: str) -> None: ...
