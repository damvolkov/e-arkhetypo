"""ports/telemetry: tracing — a span opened around a block, written until it ends, settled by how the block left."""

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

    def status(self, status: SpanStatus, description: str = "") -> None:
        """Settle the verdict explicitly; a clean exit settles OK, a raise settles ERROR on its own."""
        ...


@runtime_checkable
class TelemetryPort(Provider, Protocol):
    """Tracing: open a span around a block; a raise inside is recorded on the span, then propagates."""

    def span(
        self, name: str, attributes: Mapping[str, AttributeValue], kind: SpanKind = SpanKind.INTERNAL
    ) -> AbstractContextManager[SpanPort]: ...
