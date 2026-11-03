"""ports/documents: document conversion — a URL, raw bytes or a local file in, its structured forms out."""

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

import msgspec

from e_infra.ports.provider import Provider

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


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
class DocumentPort(Provider, Protocol):
    """Document conversion, in the library or on a server alike.

    `options` overrides the configured conversion per call, in the converter's own option names."""

    async def convert(
        self, source: str | bytes | Path, *, filename: str = "", options: Mapping[str, object] | None = None
    ) -> DocumentConversion: ...
