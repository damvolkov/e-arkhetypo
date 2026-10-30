"""tests/unit/e_infra/processors/doc: the hybrid reader — signals, routing, spans, per-span options, merge, fallback.

The fixture is real: four pages cut from Apple's 10-K FY2025 (Item 1 text, the workforce page, the
statement of operations, and that statement again as a scan) read by the real liteparse, and a fake
port that answers each docling span with the real docling conversion of the same file, cut to the span —
so routing and merging are tested on real engines' output, offline."""

import gzip
from pathlib import Path
from typing import Any, ClassVar, Self

import anyio
import msgspec
import polars as pl
import pytest

from e_infra.infra.config.processors.doc import DocMode, DocSettings, DocSignal
from e_infra.infra.config.providers.drivers.documents.docling import DoclingTables
from e_infra.ports.documents import DocumentConversion
from e_infra.ports.provider import Isolation, Locality, ProviderSpec, Workload
from e_infra.processors.doc import BREAK, DocProcessor
from e_infra.processors.models import Backend, Document, Section
from unit.e_infra.processors.conftest import opened

RESOURCES = Path(__file__).resolve().parents[3] / "resources"
FILING = RESOURCES / "documents" / "filing.pdf"
GOLDEN = msgspec.json.decode(
    gzip.decompress((RESOURCES / "conversions" / "filing.json.gz").read_bytes()), type=DocumentConversion
)
TEXT, WORKFORCE, STATEMENT, SCAN = 1, 2, 3, 4


class FakePort:
    """docling-serve as the processor sees it: one conversion per span, cut from the golden one; calls kept."""

    spec: ClassVar[ProviderSpec] = ProviderSpec("fake", Locality.REMOTE, Workload.IO_BOUND, Isolation.LOOP)

    def __init__(self, *, fail: frozenset[int] = frozenset(), delay: float = 0.0) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail, self.delay = fail, delay
        self.flight = self.peak = 0

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Nothing to release."""

    async def health(self) -> bool:
        return True

    async def convert(self, source: Any, *, filename: str = "", options: Any = None) -> DocumentConversion:
        self.calls.append({"filename": filename, "options": dict(options or {}), "size": len(source)})
        self.flight += 1
        self.peak = max(self.peak, self.flight)
        try:
            await anyio.sleep(self.delay)
            first, last = options["page_range"]
            if self.fail & set(range(first, last + 1)):
                msg = f"pages {first}-{last} refused"
                raise RuntimeError(msg)
            parts = GOLDEN.markdown.split(BREAK)[first - 1 : last]
            return msgspec.structs.replace(GOLDEN, markdown=BREAK.join(parts))
        finally:
            self.flight -= 1


def processor(port: FakePort | None = None, **conf: Any) -> DocProcessor:
    settings = DocSettings(**conf)
    return DocProcessor(port or FakePort(), opened(), settings)


##### SIGNALS AND ROUTING #####
@pytest.mark.parametrize(
    ("mode", "route", "expected"),
    [
        (DocMode.LITE, (DocSignal.TABLE,), []),
        (DocMode.DEEP, (), [1, 2, 3, 4]),
        (DocMode.HYBRID, (DocSignal.TABLE,), [3]),
        (DocMode.HYBRID, (DocSignal.SCANNED,), [4]),
        (DocMode.HYBRID, (DocSignal.COLUMNS,), []),
    ],
)
def test_route_follows_mode_and_signals(mode: DocMode, route: tuple[DocSignal, ...], expected: list[int]) -> None:
    signals = {1: (), 2: (), 3: (DocSignal.TABLE, DocSignal.GRAPHICS), 4: (DocSignal.SCANNED,)}
    assert processor(mode=mode, route=route)._process_route(signals) == expected


@pytest.mark.parametrize(
    ("pages", "conf", "spans"),
    [
        ([], {}, []),
        ([5], {}, [(5, 5)]),
        ([3, 5, 9], {"gap": 1}, [(3, 5), (9, 9)]),
        ([3, 5, 9], {"gap": 0}, [(3, 3), (5, 5), (9, 9)]),
        ([3, 5, 9], {"gap": 3, "concurrency": 1}, [(3, 9)]),
        ([3, 5, 9], {"gap": 3}, [(3, 5), (6, 9)]),
        ### a two-page run stays one request: halving it costs more than the second lane returns.
        ([3, 4], {"concurrency": 4}, [(3, 4)]),
        ### one long run, two lanes: cut in balanced halves so both server workers take one.
        (list(range(10, 30)), {"concurrency": 2}, [(10, 19), (20, 29)]),
        (list(range(10, 30)), {"concurrency": 1, "span": 8}, [(10, 17), (18, 25), (26, 29)]),
    ],
)
def test_spans_merge_gaps_and_balance_lanes(
    pages: list[int], conf: dict[str, Any], spans: list[tuple[int, int]]
) -> None:
    assert processor(**conf)._process_spans(pages) == spans


@pytest.mark.parametrize(
    ("signals", "ocr", "pictures"),
    [
        ({3: (DocSignal.TABLE,)}, False, False),
        ({3: (DocSignal.TABLE,), 4: (DocSignal.SCANNED,)}, True, False),
        ({3: (DocSignal.GRAPHICS,)}, False, True),
        ({4: (DocSignal.IMAGES,)}, False, True),
    ],
)
def test_a_span_asks_only_what_its_pages_need(
    signals: dict[int, tuple[DocSignal, ...]], ocr: bool, pictures: bool
) -> None:
    options = processor(tables=DoclingTables.FAST)._process_options((3, 4), signals)
    assert (options["page_range"], options["do_ocr"], options["table_mode"]) == ([3, 4], ocr, "fast")
    assert options["md_page_break_placeholder"] == BREAK
    assert ("image_export_mode" not in options) is pictures


##### PROCESS — the merged reading #####
async def test_hybrid_reads_each_page_with_its_engine() -> None:
    port = FakePort()
    document = await processor(port).process(FILING)
    assert isinstance(document, Document)
    assert (document.name, [page.backend for page in document.pages]) == (
        "filing.pdf",
        [Backend.LITEPARSE, Backend.LITEPARSE, Backend.DOCLING, Backend.DOCLING],
    )
    assert document.deep == (STATEMENT, SCAN)
    ### pages 3 and 4 are adjacent: one request carries both, OCR on for the scan.
    assert [call["options"]["page_range"] for call in port.calls] == [[3, 4]]
    assert port.calls[0]["options"]["do_ocr"] is True
    assert {page.number: page.signals for page in document.pages}[STATEMENT][0] is DocSignal.TABLE


async def test_tables_come_from_the_engine_of_their_page() -> None:
    document = await processor().process(FILING)
    tables = {table.page: table for table in document.tables}
    assert set(tables) == {STATEMENT, SCAN}
    assert tables[STATEMENT].shape[0] > 10
    assert {table.backend for table in tables.values()} == {Backend.DOCLING}
    rows = tables[STATEMENT].frame.select(pl.concat_str(pl.all(), separator=" | ")).to_series()
    assert rows.str.contains("Net income.*112,010").any()
    ### the scan, read by docling's OCR, keeps its table structure.
    scanned = tables[SCAN].frame.select(pl.concat_str(pl.all(), separator=" | ")).to_series()
    assert scanned.str.contains("112,010").any()
    assert all(table.ref.startswith("docling:3-4#/tables/") for table in tables.values())


async def test_items_are_one_frame_across_engines() -> None:
    document = await processor().process(FILING)
    items = document.items
    assert items.columns == ["ref", "page", "label", "text", "level", "backend"]
    assert items["page"].is_sorted()
    assert set(items.filter(pl.col("page") <= WORKFORCE)["backend"]) == {"liteparse"}
    assert set(items.filter(pl.col("page") >= STATEMENT)["backend"]) == {"docling"}
    assert items["text"].str.contains("full-time equivalent employees").any()
    assert items.filter(pl.col("backend") == "liteparse")["ref"].str.starts_with("liteparse:p").all()


async def test_markdown_is_each_pages_own() -> None:
    document = await processor().process(FILING)
    pages = {page.number: page.markdown for page in document.pages}
    assert "112,010" in pages[STATEMENT]
    assert "112,010" not in pages[TEXT]
    assert document.markdown.count("112,010") >= 2
    assert all(pages.values())


async def test_lite_mode_never_calls_docling_and_reads_tables_itself() -> None:
    port = FakePort()
    document = await processor(port, mode=DocMode.LITE).process(FILING.read_bytes(), name="raw.pdf")
    assert port.calls == []
    assert (document.name, document.deep) == ("raw.pdf", ())
    assert {table.backend for table in document.tables} == {Backend.LITEPARSE}
    assert any(table.page == STATEMENT for table in document.tables)


async def test_a_failed_span_falls_back_to_liteparse_with_its_reason() -> None:
    port = FakePort(fail=frozenset({SCAN}))
    document = await processor(port, span=1).process(FILING)
    pages = {page.number: page for page in document.pages}
    assert (pages[STATEMENT].backend, pages[SCAN].backend) == (Backend.DOCLING, Backend.LITEPARSE)
    assert pages[SCAN].fallback == "RuntimeError: pages 4-4 refused"
    assert pages[STATEMENT].fallback == ""


async def test_deep_requests_stay_within_the_concurrency_bound() -> None:
    port = FakePort(delay=0.05)
    await processor(port, mode=DocMode.DEEP, gap=0, concurrency=2, span=1).process(FILING)
    assert (len(port.calls), port.peak) == (4, 2)


async def test_a_span_with_unsplittable_markdown_keeps_liteparse_markdown() -> None:
    class Whole(FakePort):
        async def convert(self, source: Any, *, filename: str = "", options: Any = None) -> DocumentConversion:
            return msgspec.structs.replace(
                await super().convert(source, filename=filename, options=options), markdown="one blob"
            )

    document = await processor(Whole()).process(FILING)
    statement = next(page for page in document.pages if page.number == STATEMENT)
    assert statement.backend is Backend.DOCLING
    assert statement.markdown != "one blob"
    assert "112,010" in statement.markdown


##### READS — sections and frames #####
async def test_sections_span_engines() -> None:
    document = await processor().process(FILING)
    sections = DocProcessor.sections(document)
    assert all(isinstance(section, Section) for section in sections)
    assert any(section.title.startswith("Item 1") and section.text for section in sections)
    assert [section.page for section in sections] == sorted(section.page for section in sections)


def test_header_rows_fold_into_unique_padded_columns() -> None:
    frame = DocProcessor._common_frame(
        [["Item", "2025", "2025"], ["", "Q1", "Q1"]], [["Sales", "10"], ["Cost", "4", "5"]]
    )
    assert frame.columns == ["Item", "2025 Q1", "2025 Q1_1"]
    assert frame.rows() == [("Sales", "10", ""), ("Cost", "4", "5")]
    assert DocProcessor._common_frame([], []).shape == (0, 0)


def test_docling_pictures_decode_and_rank_classes() -> None:
    png = b"\x89PNG\r\n\x1a\n"
    node = {
        "image": {
            "mimetype": "image/png",
            "uri": "data:image/png;base64,iVBORw0KGgo=",
            "size": {"width": 3.0, "height": 2.0},
        },
        "annotations": [
            {
                "kind": "classification",
                "predicted_classes": [
                    {"class_name": "logo", "confidence": 0.2},
                    {"class_name": "chart", "confidence": 0.7},
                ],
            },
            {"kind": "description"},
        ],
    }
    assert DocProcessor._deep_image(node) == {"mimetype": "image/png", "data": png, "width": 3, "height": 2}
    assert DocProcessor._deep_classes(node) == ("chart", "logo")
    assert DocProcessor._deep_image({}) == {"mimetype": "", "data": b"", "width": 0, "height": 0}


def test_a_node_without_provenance_sits_on_no_page() -> None:
    assert DocProcessor._common_page({}) == 0
