"""ports/documents: document conversion — a URL, raw bytes or a local file in, its structured forms out."""

from collections.abc import Mapping
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import msgspec

from e_infra.ports.provider import Provider

if TYPE_CHECKING:
    from pathlib import Path

    from e_infra.infra.payload import JSON


### msgspec cannot type JSON recursively: a document is a mapping of any JSON value.
type Document = Mapping[str, object]  # ast-grep-ignore: object-annotation


class DocumentConversion(msgspec.Struct, frozen=True, kw_only=True):
    """One document converted: the forms asked for (absent ones None), the outcome, and what it cost.

    `document` is the lossless DoclingDocument as JSON — every text, table, picture and its provenance;
    `markdown`, `html`, `text` and `doctags` are its renderings. `status` is the converter's own
    (`success`, `partial_success`); `errors` carries what a partial conversion lost."""

    filename: str | None = None
    status: str | None = None
    markdown: str | None = None
    document: Document = msgspec.field(default_factory=dict)
    html: str | None = None
    text: str | None = None
    doctags: str | None = None
    errors: tuple[Document, ...] = ()
    seconds: float = 0.0


@runtime_checkable
class DocumentPort(Provider, Protocol):
    """Document conversion, in the library or on a server alike.

    `options` overrides the configured conversion per call, in the converter's own option names."""

    async def convert(
        self, source: str | bytes | Path, *, filename: str | None = None, options: Mapping[str, JSON] | None = None
    ) -> DocumentConversion: ...
