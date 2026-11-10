"""ports/telemetry: tracing — a span opened around a block, written until it ends, settled by how the block left.

The vocabulary is the service's, never a vendor's: a span may carry a `SpanRole` (what kind of work it times) and
attributes keyed by `SpanKey` (a meaning) or a free dotted name; the provider translates role and keys into its own
conventions. `carrier` and `resume` move a trace across a queue or a process as an opaque mapping."""

from enum import StrEnum, auto
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from e_infra.ports.provider import Provider

if TYPE_CHECKING:
    from collections.abc import Mapping
    from contextlib import AbstractContextManager

type AttributeValue = str | bool | int | float


##### VALUES #####
class SpanKind(StrEnum):
    """The span's role in a call: work inside a process, or one side of a remote exchange."""

    INTERNAL = auto()
    SERVER = auto()
    CLIENT = auto()
    PRODUCER = auto()
    CONSUMER = auto()


class SpanRole(StrEnum):
    """What a span times: a request at a door, a background job, a model call, an embedding, a retrieval, any other
    call. A role picks the span's kind and its convention in the provider."""

    REQUEST = auto()
    JOB = auto()
    LLM = auto()
    EMBEDDING = auto()
    RETRIEVER = auto()
    CALL = auto()


class SpanKey(StrEnum):
    """Attribute keys with a meaning a provider names its own way (per role where they differ); any other key passes
    as written."""

    INPUT = auto()
    OUTPUT = auto()
    MODEL = auto()
    SIZE = auto()
    BATCH = auto()
    HITS = auto()
    TOKENS = auto()
    STATUS = auto()


class SpanStatus(StrEnum):
    """A span's verdict: left unset, explicitly fine, or failed."""

    UNSET = auto()
    OK = auto()
    ERROR = auto()


##### PORTS #####
@runtime_checkable
class SpanPort(Protocol):
    """An open span: its W3C hex ids, and what may still be written on it before it ends."""

    @property
    def trace_id(self) -> str: ...

    @property
    def span_id(self) -> str: ...

    def record(self, attributes: Mapping[str, AttributeValue]) -> None:
        """Set attributes known only once the work ran — its output, its outcome."""
        ...

    def event(self, name: str, attributes: Mapping[str, AttributeValue]) -> None:
        """A timestamped point inside the span."""
        ...

    def status(self, status: SpanStatus, description: str | None = None) -> None:
        """Settle the verdict explicitly; a clean exit settles OK, a raise settles ERROR on its own."""
        ...


@runtime_checkable
class TelemetryPort(Provider, Protocol):
    """Tracing: open a span around a block; a raise inside is recorded on the span, then propagates. Without a `role`
    the span is of `kind` and its attributes as written; with one, the role decides the kind and the keys are named in
    the provider's convention. `carrier` is the current trace as an opaque mapping to send along; `resume` runs a
    block as the child of a carrier's trace."""

    def span(
        self,
        name: str,
        attributes: Mapping[str, AttributeValue],
        kind: SpanKind = SpanKind.INTERNAL,
        *,
        role: SpanRole | None = None,
    ) -> AbstractContextManager[SpanPort]: ...

    def carrier(self) -> dict[str, str]: ...

    def resume(self, carrier: Mapping[str, str]) -> AbstractContextManager[None]: ...
