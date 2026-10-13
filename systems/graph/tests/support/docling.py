"""tests/support/docling: docling-serve, offline — the golden conversions of the corpus, served as the port serves.

`GoldenPort` satisfies `DocumentPort` by shape. Asked to convert a corpus document (matched by file
name stem), it answers with what the live docling-serve made of it (`tests/resources/conversions`,
`make conversions`): the whole conversion, whose nodes carry their own page numbers — the processor
keeps only the pages of the span it asked for. Every call is recorded, so a test sees what was routed."""

import gzip
from pathlib import Path
from typing import Any, ClassVar, Final

import msgspec

from adapters.ports import DocumentConversion

CONVERSIONS: Final[Path] = Path(__file__).resolve().parents[1] / "resources" / "conversions"


class GoldenPort:
    """A document port backed by the golden conversions; `calls` keeps every request's filename and options."""

    name: ClassVar[str] = "docling"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._cache: dict[str, DocumentConversion] = {}

    async def convert(self, source: Any, *, filename: str = "", options: Any = None) -> DocumentConversion:
        self.calls.append({"filename": filename, "options": dict(options or {})})
        stem = filename.removesuffix(".pdf")
        match self._cache.get(stem):
            case None:
                raw = gzip.decompress((CONVERSIONS / f"{stem}.json.gz").read_bytes())
                conversion = self._cache[stem] = msgspec.json.decode(raw, type=DocumentConversion)
                return conversion
            case cached:
                return cached
