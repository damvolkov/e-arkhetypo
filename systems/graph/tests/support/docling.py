"""tests/support/docling: docling-serve, offline — the corpus's recorded spans, served as the port serves.

`GoldenPort` satisfies `DocumentPort` by shape. Asked to convert a span of a corpus document (matched by
file name stem and `page_range`), it answers with what the live docling-serve answered for that very
span (`tests/resources/conversions`, `make conversions`): its nodes, its tables, its markdown. A span
never recorded fails as the service would, and the processor falls back to liteparse for it. Every
call is recorded, so a test sees what was routed."""

import gzip
from pathlib import Path
from typing import Any, ClassVar, Final

import msgspec

from adapters.ports import DocumentConversion

CONVERSIONS: Final[Path] = Path(__file__).resolve().parents[1] / "resources" / "conversions"


class GoldenPort:
    """A document port backed by the recorded spans; `calls` keeps every request's filename and options."""

    name: ClassVar[str] = "docling"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._spans: dict[str, dict[str, DocumentConversion]] = {}

    def _convert_spans(self, stem: str) -> dict[str, DocumentConversion]:
        match self._spans.get(stem):
            case None:
                raw = gzip.decompress((CONVERSIONS / f"{stem}.json.gz").read_bytes())
                spans = self._spans[stem] = msgspec.json.decode(raw, type=dict[str, DocumentConversion])
                return spans
            case spans:
                return spans

    async def convert(self, source: Any, *, filename: str = "", options: Any = None) -> DocumentConversion:
        self.calls.append({"filename": filename, "options": dict(options or {})})
        first, last = dict(options or {})["page_range"]
        match self._convert_spans(filename.removesuffix(".pdf")).get(f"{first}-{last}"):
            case None:
                msg = f"{filename}: span {first}-{last} was never recorded (make conversions)"
                raise KeyError(msg)
            case conversion:
                return conversion
