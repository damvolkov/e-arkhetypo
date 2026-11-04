"""tests/unit/e_infra/processors/doc: the reader — engines by presence and format, routing, spans, merge, fallback.

The fixture is real: four pages cut from Apple's 10-K FY2025 (Item 1 text, the workforce page, the
statement of operations, and that statement again as a scan) read by the real liteparse, and a fake
port that answers each docling span with the real docling conversion of the same file, cut to the span —
so routing and merging are tested on real engines' output, offline. Any other format meets a fake `MarkdownPort`
whose *detection* is the real anytomd binding; docling absent is the processor built without its port."""

import gzip
import io
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Self

import anyio
import msgspec
import polars as pl
import pytest

from e_infra.infra.config.processors.doc import DocMode, DocSettings, DocSignal
from e_infra.infra.config.providers.adapters.markdown.anytomd import AnytomdSettings
from e_infra.infra.config.providers.drivers.documents.docling import DoclingTables
from e_infra.infra.errors import DocumentError, InputTooLargeError, UnsupportedFormatError
from e_infra.ports.documents import DocumentConversion
from e_infra.ports.markdown import MDConversion
from e_infra.ports.pages import FastPage, PageBlock
from e_infra.ports.provider import Isolation, Locality, ProviderSpec, Workload
from e_infra.processors.doc import BREAK, EVERY, DocProcessor
from e_infra.processors.models import Backend, Document, Element, Section
from e_infra.providers.adapters.markdown.anytomd import AnytomdAdapter
from unit.e_infra.processors.conftest import opened

if TYPE_CHECKING:
    from unit.e_infra.conftest import Logs

RESOURCES = Path(__file__).resolve().parents[3] / "resources"
FILING = RESOURCES / "documents" / "filing.pdf"
GOLDEN = msgspec.json.decode(
    gzip.decompress((RESOURCES / "conversions" / "filing.json.gz").read_bytes()), type=DocumentConversion
)
TEXT, WORKFORCE, STATEMENT, SCAN = 1, 2, 3, 4
DETECTOR = AnytomdAdapter(AnytomdSettings())
MARKDOWN = "# Title\n\nFirst paragraph.\n\n## Sub\n\nSecond,\nstill second."


class FakePort:
    """docling-serve as the processor sees it: one conversion per span, cut from the golden one; calls kept."""

    spec: ClassVar[ProviderSpec] = ProviderSpec("fake", Locality.REMOTE, Workload.IO_BOUND, Isolation.LOOP)

    def __init__(self, *, fail: frozenset[int] = frozenset(), refuse: bool = False, delay: float = 0.0) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail, self.refuse, self.delay = fail, refuse, delay
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
            match (dict(options or {}).get("page_range"), self.refuse):
                case (None, True):
                    msg = "docling refused"
                    raise DocumentError(msg)
                case (None, False):
                    return GOLDEN
                case ((first, last), _) if self.fail & set(range(first, last + 1)):
                    msg = f"pages {first}-{last} refused"
                    raise DocumentError(msg)
                case ((first, last), _):
                    parts = GOLDEN.markdown.split(BREAK)[first - 1 : last]
                    return msgspec.structs.replace(GOLDEN, markdown=BREAK.join(parts))
                case other:
                    msg = f"no conversion scripted for {other}"
                    raise AssertionError(msg)
        finally:
            self.flight -= 1


class FakeMarkdown:
    """anytomd as the processor sees it: the real detection, a fixed rendering, its warnings; calls kept."""

    spec: ClassVar[ProviderSpec] = ProviderSpec("fake-md", Locality.EMBEDDED, Workload.MIXED, Isolation.LOOP)

    def __init__(self, markdown: str = MARKDOWN, warnings: tuple[str, ...] = ()) -> None:
        self.markdown, self.warnings = markdown, warnings
        self.calls: list[tuple[bytes, str]] = []

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Nothing to release."""

    async def health(self) -> bool:
        return True

    def detect(self, name: str, data: bytes) -> str | None:
        return DETECTOR.detect(name, data)

    async def convert(self, data: bytes, *, extension: str) -> MDConversion:
        self.calls.append((data, extension))
        return MDConversion(markdown=self.markdown, warnings=self.warnings)


def zipped(files: dict[str, bytes]) -> bytes:
    """A deterministic ZIP: a frozen date_time keeps the bytes stable."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        _ = [archive.writestr(zipfile.ZipInfo(n, date_time=(1980, 1, 1, 0, 0, 0)), raw) for n, raw in files.items()]
    return buf.getvalue()


DOCX = zipped({"word/document.xml": b"<w/>"})


def processor(port: FakePort | None = None, *, markdown: FakeMarkdown | None = None, **conf: Any) -> DocProcessor:
    """The reader with docling present (a fake one unless given)."""
    return DocProcessor(markdown or FakeMarkdown(), opened(), port or FakePort(), DocSettings(**conf))


def without_docling(markdown: FakeMarkdown | None = None, **conf: Any) -> DocProcessor:
    """The reader as the lifespan builds it when DOCLING_URL is unset or docling is down: no deep port."""
    return DocProcessor(markdown or FakeMarkdown(), opened(), None, DocSettings(**conf))


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
    assert processor(mode=mode, route=route)._process_route(signals, EVERY) == expected


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
    options = processor(tables=DoclingTables.FAST)._process_options((3, 4), signals, EVERY)
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
    assert items.columns == ["ref", "page", "label", "text", "level", "backend", "group", "hyperlink"]
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


async def test_a_failed_span_falls_back_to_liteparse_with_its_reason_said_nowhere_else(logs: Logs) -> None:
    port = FakePort(fail=frozenset({SCAN}))
    document = await processor(port, span=1).process(FILING)
    pages = {page.number: page for page in document.pages}
    assert (pages[STATEMENT].backend, pages[SCAN].backend) == (Backend.DOCLING, Backend.LITEPARSE)
    assert pages[SCAN].fallback == "DocumentError: pages 4-4 refused"
    assert (pages[STATEMENT].fallback, logs.at("warning")) == ("", [])


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
    sections = document.sections
    assert all(isinstance(section, Section) for section in sections)
    assert any(section.title.startswith("Item 1") and section.text for section in sections)
    assert [section.page for section in sections] == sorted(section.page for section in sections)


def test_header_rows_fold_into_unique_padded_columns() -> None:
    frame = DocProcessor._process_frame(
        [["Item", "2025", "2025"], ["", "Q1", "Q1"]], [["Sales", "10"], ["Cost", "4", "5"]]
    )
    assert frame.columns == ["Item", "2025 Q1", "2025 Q1_1"]
    assert frame.rows() == [("Sales", "10", ""), ("Cost", "4", "5")]
    assert DocProcessor._process_frame([], []).shape == (0, 0)


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
    picture = DocProcessor._process_picture({}, {**node, "self_ref": "#/pictures/0"}, "docling:", 2)
    assert (picture.ref, picture.page, picture.mimetype, picture.data) == ("docling:#/pictures/0", 2, "image/png", png)
    assert (picture.width, picture.height, picture.classes) == (3, 2, ("chart", "logo"))
    empty = DocProcessor._process_picture({}, {"self_ref": "#/pictures/1"}, "", 1)
    assert (empty.mimetype, empty.data, empty.width, empty.height, empty.classes) == ("", b"", 0, 0, ())


@pytest.mark.parametrize(
    ("node", "span", "page"),
    [({}, (1, 9), 0), ({"prov": [{"page_no": 7}]}, (1, 9), 7), ({"prov": [{"page_no": 7}]}, (8, 9), 0), ({}, None, 1)],
    ids=["unplaced", "in-span", "off-span", "whole"],
)
def test_a_node_is_placed_on_its_page_in_the_span_or_on_none(node: dict[str, Any], span: Any, page: int) -> None:
    assert DocProcessor._process_place(node, span) == page


##### LABELS — nothing a reader saw is dropped #####
def test_a_fast_page_keeps_every_block_its_shared_kinds_named_as_docling_names_them() -> None:
    blocks = (
        PageBlock(kind="heading", text="Risk", level=1),
        PageBlock(kind="paragraph", text="body"),
        PageBlock(kind="rule"),
        PageBlock(kind="grid_fallback", text="a | b"),
        PageBlock(kind="table", header=("h",), rows=(("v",),)),
    )
    page = FastPage(number=3, markdown="", blocks=blocks, signals=())
    _, (rows, tables, _, _) = DocProcessor._process_fast(page)
    assert [(row["label"], row["group"], row["hyperlink"]) for row in rows] == [
        ("section_header", "", ""),
        ("text", "", ""),
        ("rule", "", ""),
        ("grid_fallback", "", ""),
    ]
    assert [table.ref for table in tables] == ["liteparse:p3/b4"]


@pytest.mark.parametrize(
    ("parent", "group"),
    [({"$ref": "#/groups/1"}, "slide"), ({"$ref": "#/body"}, ""), (None, "")],
    ids=["grouped", "body", "orphan"],
)
def test_a_deep_node_names_the_group_it_sits_in(parent: dict[str, str] | None, group: str) -> None:
    document = {"groups": [{"label": "list"}, {"label": "slide"}]}
    node = {"parent": parent, "self_ref": "#/texts/0", "label": "text"}
    assert DocProcessor._process_item(document, node, "", 1)["group"] == group


##### ENGINES — docling when present; liteparse and anytomd always #####
@pytest.mark.parametrize("mode", [DocMode.HYBRID, DocMode.DEEP])
async def test_without_docling_every_pdf_page_is_liteparse_whatever_the_mode(mode: DocMode) -> None:
    document = await without_docling(mode=mode).process(FILING)
    assert {page.backend for page in document.pages} == {Backend.LITEPARSE}
    assert (document.deep, {page.fallback for page in document.pages}) == ((), {""})
    assert any(table.page == STATEMENT for table in document.tables)


async def test_a_pdf_never_reaches_anytomd() -> None:
    markdown = FakeMarkdown()
    await processor(markdown=markdown).process(FILING)
    assert markdown.calls == []


@pytest.mark.parametrize(("data", "name"), [(b"<h1>x</h1>", "p.html"), (DOCX, "r.docx")])
async def test_a_format_docling_reads_goes_whole_to_docling(data: bytes, name: str) -> None:
    port, markdown = FakePort(), FakeMarkdown()
    document = await processor(port, markdown=markdown).process(data, name=name)
    assert ([(call["filename"], call["options"]) for call in port.calls], markdown.calls) == ([(name, {})], [])
    assert [(page.number, page.backend) for page in document.pages] == [(1, Backend.DOCLING)]
    assert (len(document.tables), len(document.pictures)) == (
        len(GOLDEN.document["tables"]),
        len(GOLDEN.document["pictures"]),
    )
    assert set(document.items["backend"]) == {Backend.DOCLING}
    assert "data:" not in document.markdown


@pytest.mark.parametrize(("data", "name", "extension"), [(b"# t\n\nbody", "n.md", "md"), (b"print(1)\n", "m.py", "py")])
async def test_a_format_docling_does_not_read_goes_to_anytomd(data: bytes, name: str, extension: str) -> None:
    port, markdown = FakePort(), FakeMarkdown()
    document = await processor(port, markdown=markdown).process(data, name=name)
    assert (port.calls, markdown.calls) == ([], [(data, extension)])
    assert [(page.number, page.backend, page.markdown) for page in document.pages] == [(1, Backend.ANYTOMD, MARKDOWN)]
    assert (document.name, document.tables, document.deep) == (name, (), ())


async def test_docling_refusing_a_document_hands_it_to_anytomd_with_its_reason(logs: Logs) -> None:
    port, markdown = FakePort(refuse=True), FakeMarkdown()
    document = await processor(port, markdown=markdown).process(DOCX, name="r.docx")
    assert (len(port.calls), markdown.calls) == (1, [(DOCX, "docx")])
    assert [(page.backend, page.fallback) for page in document.pages] == [
        (Backend.ANYTOMD, "DocumentError: docling refused")
    ]
    assert logs.at("warning") == []


async def test_lite_mode_reads_every_other_format_with_anytomd() -> None:
    port, markdown = FakePort(), FakeMarkdown()
    await processor(port, markdown=markdown, mode=DocMode.LITE).process(DOCX, name="r.docx")
    assert (port.calls, markdown.calls) == ([], [(DOCX, "docx")])


async def test_anytomd_markdown_becomes_items_and_sections() -> None:
    document = await without_docling().process(b"<h1>x</h1>", name="p.html")
    assert document.items.select("ref", "label", "text", "level").rows() == [
        ("anytomd:b0", "section_header", "Title", 1),
        ("anytomd:b1", "text", "First paragraph.", None),
        ("anytomd:b2", "section_header", "Sub", 2),
        ("anytomd:b3", "text", "Second,\nstill second.", None),
    ]
    assert [(s.title, s.level, s.text) for s in document.sections] == [
        ("Title", 1, "First paragraph."),
        ("Sub", 2, "Second,\nstill second."),
    ]


async def test_anytomd_warnings_ride_on_the_document() -> None:
    document = await without_docling(FakeMarkdown(warnings=("image skipped",))).process(b"<p>x</p>", name="p.html")
    assert document.warnings == ("image skipped",)


@pytest.mark.parametrize(
    "data", [b"\x00\x01\x02\xff" * 8, zipped({"a.txt": b"x", "b.txt": b"y"})], ids=["noise", "zip"]
)
async def test_an_unsupported_file_or_an_archive_is_refused_before_any_engine(data: bytes) -> None:
    port, markdown = FakePort(), FakeMarkdown()
    with pytest.raises(UnsupportedFormatError):
        await processor(port, markdown=markdown).process(data, name="blob")
    assert (port.calls, markdown.calls) == ([], [])


async def test_an_oversized_file_is_refused() -> None:
    with pytest.raises(InputTooLargeError):
        await processor(max_input_bytes=4).process(b"<h1>too long</h1>", name="p.html")


async def test_bytes_without_a_name_are_named_document_and_detected_by_their_magic() -> None:
    document = await without_docling().process(FILING.read_bytes())
    assert (document.name, document.pages[0].backend) == ("document", Backend.LITEPARSE)


##### ELEMENTS — one asked, only its cost paid #####
@pytest.mark.parametrize(
    ("elements", "expected"),
    [
        ({Element.TEXT}, [4]),
        ({Element.TABLES}, [2, 4]),
        ({Element.PICTURES}, [3]),
        ({Element.FORMULAS}, [2, 3, 4]),
        (set(Element), [2, 3, 4]),
    ],
    ids=["text", "tables", "pictures", "formulas", "every"],
)
def test_route_narrows_to_what_the_elements_need(elements: set[Element], expected: list[int]) -> None:
    signals = {1: (), 2: (DocSignal.TABLE,), 3: (DocSignal.GRAPHICS,), 4: (DocSignal.SCANNED,)}
    assert processor()._process_route(signals, frozenset(elements)) == expected


@pytest.mark.parametrize(
    ("elements", "structure", "pictures"),
    [({Element.TABLES}, True, False), ({Element.PICTURES}, False, True), ({Element.TEXT}, False, False)],
    ids=["tables", "pictures", "text"],
)
def test_a_span_runs_no_model_its_elements_do_not_need(elements: set[Element], structure: bool, pictures: bool) -> None:
    options = processor()._process_options((3, 3), {3: (DocSignal.GRAPHICS,)}, frozenset(elements))
    assert (options.get("do_table_structure", True), "image_export_mode" not in options) == (structure, pictures)


async def test_text_asks_docling_for_the_scan_alone_and_no_table_structure() -> None:
    port = FakePort()
    text = await processor(port).text(FILING)
    assert [call["options"]["page_range"] for call in port.calls] == [[SCAN, SCAN]]
    assert port.calls[0]["options"]["do_table_structure"] is False
    assert "full-time equivalent employees" in text


async def test_tables_ask_docling_for_table_pages_without_pictures() -> None:
    port = FakePort()
    tables = await processor(port).tables(FILING)
    options = port.calls[0]["options"]
    assert [call["options"]["page_range"] for call in port.calls] == [[STATEMENT, SCAN]]
    assert (options["image_export_mode"], "do_table_structure" in options) == ("placeholder", False)
    assert {table.page for table in tables} == {STATEMENT, SCAN}


async def test_pictures_and_formulas_come_from_docling_alone() -> None:
    assert (await without_docling().pictures(FILING), await without_docling().formulas(FILING)) == ((), ())


async def test_sections_read_from_a_source_as_text_reads() -> None:
    port = FakePort()
    sections = await processor(port).sections(FILING)
    assert any(section.title.startswith("Item 1") and section.text for section in sections)
    assert [call["options"]["page_range"] for call in port.calls] == [[SCAN, SCAN]]


async def test_a_whole_document_drops_what_is_not_asked() -> None:
    port = FakePort()
    await processor(port).text(DOCX, name="r.docx")
    assert port.calls[0]["options"] == {
        "do_table_structure": False,
        "image_export_mode": "placeholder",
        "include_images": False,
    }


async def test_an_oversized_path_is_refused_before_it_is_read(tmp_path: Path) -> None:
    path = tmp_path / "big.pdf"
    path.write_bytes(FILING.read_bytes())
    with pytest.raises(InputTooLargeError, match=str(path.stat().st_size)):
        await processor(max_input_bytes=1024).process(path)
