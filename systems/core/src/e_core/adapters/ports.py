"""adapters/ports: what consumers (routers, deps, lifespan) may ask of an external service.

Structural contracts only — a Protocol, never an ABC: an adapter satisfies its port by shape,
and swapping redis for sqlite edits one wiring line, zero domain code."""

from enum import StrEnum, auto
from typing import TYPE_CHECKING, Any, ClassVar, Protocol, runtime_checkable

import msgspec

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping
    from contextlib import AbstractContextManager
    from pathlib import Path

type AttributeValue = str | bool | int | float


##### TYPES #####
@runtime_checkable
class StorePort(Protocol):
    """Byte-keyed store: point reads, writes, deletes and a lazy key scan — the whole CRUD a consumer sees."""

    name: ClassVar[str]

    async def get(self, key: str) -> bytes | None:
        """Missing key reads as None, never an exception."""
        ...

    async def set(self, key: str, value: bytes) -> None: ...

    async def delete(self, key: str) -> None:
        """Missing key is a no-op."""
        ...

    def keys(self, prefix: str = "") -> AsyncIterator[str]:
        """Keys starting with `prefix`, streamed lazily: an async generator, never a materialized list."""
        ...


@runtime_checkable
class HttpPort(Protocol):
    """Outbound HTTP: GET and POST against the configured base, non-2xx raising the client's own error."""

    name: ClassVar[str]

    async def get(self, path: str) -> object: ...

    async def post(self, path: str, payload: object) -> object: ...


##### TELEMETRY #####
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
class TelemetryPort(Protocol):
    """Tracing: open a span around a block; a raise inside is recorded on the span, then propagates."""

    name: ClassVar[str]

    def span(
        self, name: str, attributes: Mapping[str, AttributeValue], kind: SpanKind = SpanKind.INTERNAL
    ) -> AbstractContextManager[SpanPort]: ...


##### DOCUMENTS #####
class DocumentConversion(msgspec.Struct, frozen=True, kw_only=True):
    """One document converted: the forms asked for (absent ones empty), the outcome, and what it cost.

    `document` is the lossless DoclingDocument as JSON — every text, table, picture and its provenance;
    `markdown`, `html`, `text` and `doctags` are its renderings. `status` is the converter's own
    (`success`, `partial_success`); `errors` carries what a partial conversion lost."""

    filename: str
    status: str
    markdown: str = ""
    document: dict[str, Any] = msgspec.field(default_factory=dict)
    html: str = ""
    text: str = ""
    doctags: str = ""
    errors: tuple[dict[str, Any], ...] = ()
    seconds: float = 0.0


@runtime_checkable
class DocumentPort(Protocol):
    """Document conversion: a URL, raw bytes or a local file in, its structured forms out.

    `options` overrides the configured conversion per call, in the converter's own option names."""

    name: ClassVar[str]

    async def convert(
        self, source: str | bytes | Path, *, filename: str = "", options: Mapping[str, object] | None = None
    ) -> DocumentConversion: ...


##### MARKDOWN #####
class MdConversion(msgspec.Struct, frozen=True, kw_only=True):
    """One file rendered to Markdown: the body, and what the converter lost along the way.

    `markdown` is the text; `warnings` are the engine's own notes about a conversion it did not fail on
    (an image it skipped, a block it could not read) — empty when the run was clean."""

    markdown: str
    warnings: tuple[str, ...] = ()


@runtime_checkable
class MdConvertPort(Protocol):
    """Render the bytes of one file, whose `extension` the caller names, to Markdown.

    The engine is the anytomd binding — it reads office documents, markup, tables, notebooks, code and text,
    and folds in PDF and image descriptions itself — so `extension` only says what the bytes are, not who will
    read them. Swapping or wrapping the engine is one wiring line and zero caller change."""

    name: ClassVar[str]

    async def convert(self, data: bytes, *, extension: str) -> MdConversion: ...
