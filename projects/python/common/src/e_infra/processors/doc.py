"""processors/doc: the DocProcessor — any document read by the engine that reads it best, among those present.

Hybrid by measurement (10-K and paper corpus, 2026-10-13). liteparse (Rust, in-process) reads a whole
filing in under a second and matches docling on running text — 98.7% of docling's words — but not on
tables: rows fused or split on ~4 in 10 table pages, captions and formulas absent. docling-serve reads
tables with TableFormer, crops and classifies pictures, OCRs scans keeping their tables, at ~1-1.7 s a
page plus ~1.8 s a request. No signal liteparse computes *before* parsing predicts which of its tables
are wrong; what it does tell, almost free, is which pages *hold* tables, figures or scans. So:

1. the fast pass (`PagesPort`: liteparse, in-process) reads every page and reports its signals per page;
2. the pages whose signals are in DOC_ROUTE — and in what the asked elements need (`NEEDS`) — go to docling, the rest
   keep liteparse's reading;
3. routed pages become spans: neighbours closer than DOC_GAP pages merge (a request costs more than the
   pages between); a long run halves into DOC_CONCURRENCY lanes when each half still pays off (`LANE`);
4. each span asks docling only for what its pages and the asked elements need — OCR for scans, pictures for figures,
   TableFormer in DOC_TABLES mode only when tables are asked — and spans convert concurrently, bounded; a failed span
   falls back to liteparse.
5. a converted span is read once: its nodes placed on their pages in one pass, its markdown split once — the
   document is the pages' readings in page order, linear in the nodes.

Every other format is read whole: by docling when it is one docling reads (`WHOLE`), by anytomd (`MarkdownPort`, our
binding) otherwise — or in docling's place when docling fails on it. anytomd's Markdown is cut into blocks, headings and
paragraphs become items, so `sections` reads any document as it reads a PDF.

`process` reads every element; `text`, `tables`, `pictures`, `formulas` and `sections` read one, and pay only for it:
text alone sends docling the scans and nothing else, tables alone never export a picture.

docling is optional: the composition root hands its driver only when DOCLING_URL is set and the server answers, and
says so once when it does not; without it every PDF page is liteparse's and every other document anytomd's, whatever
DOC_MODE asks. A fallback is never logged above debug: its reason rides on the page (`Page.fallback`). The processor
holds the ports — the anytomd adapter, the liteparse fast pass and, when present, the docling driver, singletons all —
and no state per document: `process` returns a `Document` whose objects are engine-neutral."""

import base64
import re
from itertools import chain, pairwise, takewhile
from operator import attrgetter
from pathlib import PurePath
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final, NamedTuple

import anyio
import polars as pl

from e_infra.infra.config.processors import DocMode, DocSignal
from e_infra.infra.errors import InputTooLargeError, ProviderError, UnsupportedFormatError
from e_infra.infra.logger import logger
from e_infra.ports.documents import DocumentConversion
from e_infra.processors.models import (
    Backend,
    Document,
    Element,
    Formula,
    Page,
    Picture,
    Section,
    Table,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from pathlib import Path

    from e_infra.infra.config.providers import DoclingTables
    from e_infra.ports.documents import DocumentPort
    from e_infra.ports.markdown import MarkdownPort
    from e_infra.ports.pages import FastPage, PagesPort

type Node = dict[str, Any]
type Span = tuple[int, int]
type Row = dict[str, Any]
type Signals = Mapping[int, tuple[DocSignal, ...]]

### pages a lane must keep for a second request to pay off: measured ~1.8 s a request, ~1.7 s a routed page, x1.35 from
### two in flight (docling-serve CPU, 2026-10-13) — a run splits in two only when each half keeps at least this many.
LANE: Final[int] = 2
### the break docling writes between pages in markdown: it splits a span's markdown back into its pages.
BREAK: Final[str] = "<!-- page-break -->"
### a picture embedded in markdown is bytes in a text: the bytes live in `Document.pictures`, the text keeps a marker.
EMBEDDED: Final[re.Pattern[str]] = re.compile(r"!\[[^\]]*\]\(data:[^)]*\)")
IMAGE: Final[str] = "<!-- image -->"
### liteparse block kinds onto docling's labels where they share a meaning; any other kind (a drawn `rule`, a
### `grid_fallback` the fast pass could not grid) keeps its own label: a block is never dropped here, its reader decides.
KINDS: Final[Mapping[str, str]] = MappingProxyType(
    {"heading": "section_header", "paragraph": "text", "list_item": "list_item"}
)
### a fast-pass table becomes a `Table`, never an item; every other block kind is an item, its text or its lines.
TABLE: Final[str] = "table"
### the formats docling reads whole, in anytomd's names: docling-serve's `from_formats` met with what anytomd detects
### (2026-11-04); a PDF is read page by page instead, and anything else (text, code, json, xml) is anytomd's alone.
WHOLE: Final[frozenset[str]] = frozenset({"docx", "pptx", "xlsx", "html", "csv", "image"})
### what docling fails with at its border, a deadline included: the document goes on through the other engine.
FAILURES: Final[tuple[type[Exception], ...]] = (ProviderError, TimeoutError)
### a Markdown block: blank lines apart; a heading is one to six `#` and its text.
BLOCKS: Final[re.Pattern[str]] = re.compile(r"\n\s*\n")
HEADING: Final[re.Pattern[str]] = re.compile(r"^(#{1,6})\s+(.*)$", re.DOTALL)
### the signals that make docling worth it for an element: liteparse matches docling on running text but has no text
### layer on a scan; its tables fail on table pages; it never crops a picture; no signal foretells a formula.
NEEDS: Final[Mapping[Element, frozenset[DocSignal]]] = MappingProxyType(
    {
        Element.TEXT: frozenset({DocSignal.SCANNED}),
        Element.TABLES: frozenset({DocSignal.TABLE, DocSignal.SCANNED}),
        Element.PICTURES: frozenset({DocSignal.GRAPHICS, DocSignal.IMAGES}),
        Element.FORMULAS: frozenset(DocSignal),
    }
)
### what docling is told not to run when an element is not asked: TableFormer without tables, image export without pictures.
DROPS: Final[Mapping[Element, Mapping[str, object]]] = MappingProxyType(
    {
        Element.TABLES: MappingProxyType({"do_table_structure": False}),
        Element.PICTURES: MappingProxyType({"image_export_mode": "placeholder", "include_images": False}),
    }
)
FIGURES: Final[frozenset[DocSignal]] = NEEDS[Element.PICTURES]
EVERY: Final[frozenset[Element]] = frozenset(Element)
ITEMS: Final[Mapping[str, pl.DataType]] = MappingProxyType(
    {
        "ref": pl.String(),
        "page": pl.Int64(),
        "label": pl.String(),
        "text": pl.String(),
        "level": pl.Int64(),
        "backend": pl.String(),
        "group": pl.String(),
        "hyperlink": pl.String(),
    }
)


class Reading(NamedTuple):
    """What one engine read on some pages, each object carrying its page: text items, tables, pictures, formulas."""

    rows: list[Row]
    tables: list[Table]
    pictures: list[Picture]
    formulas: list[Formula]


class DocProcessor:
    """Reads documents: a PDF page by page — liteparse everywhere, docling where present and the page's signals ask for
    it —, any other format whole — docling when present and it reads the format, anytomd otherwise or in its place."""

    __slots__ = (
        "_concurrency",
        "_gap",
        "_max_input_bytes",
        "_md",
        "_mode",
        "_pages",
        "_port",
        "_route",
        "_span",
        "_tables",
    )

    def __init__(
        self,
        markdown: MarkdownPort,
        pages: PagesPort,
        port: DocumentPort | None = None,
        *,
        concurrency: int,
        span: int,
        gap: int,
        mode: DocMode,
        route: tuple[DocSignal, ...],
        tables: DoclingTables,
        max_input_bytes: int,
    ) -> None:
        self._concurrency, self._span, self._gap, self._mode = concurrency, span, gap, mode
        self._route, self._tables, self._max_input_bytes = route, tables, max_input_bytes
        self._md = markdown
        self._pages = pages
        self._port = port

    ##### PRIVATE — the source #####

    async def _process_read(self, source: bytes | Path, name: str) -> bytes:
        """The source's bytes, refused before they are read when over DOC_MAX_INPUT_BYTES — a path by its size on disk."""
        size = len(source) if isinstance(source, bytes) else (await anyio.Path(source).stat()).st_size
        match (size > self._max_input_bytes, source):
            case (True, _):
                msg = f"{name!r} is {size} bytes, over DOC_MAX_INPUT_BYTES"
                raise InputTooLargeError(msg)
            case (_, bytes() as raw):
                return raw
            case (_, path):
                return await anyio.Path(path).read_bytes()

    ##### PRIVATE — routing #####

    def _process_route(self, signals: Signals, elements: frozenset[Element]) -> list[int]:
        """The pages docling reads, ascending: none (docling absent, or LITE), all, or those whose signals DOC_ROUTE
        names and the asked elements need."""
        route = set(self._route) & frozenset().union(*(NEEDS[element] for element in elements))
        match (self._port, self._mode):
            case (None, _) | (_, DocMode.LITE):
                return []
            case (_, DocMode.DEEP):
                return sorted(signals)
            case _:
                return sorted(page for page, seen in signals.items() if route.intersection(seen))

    def _process_spans(self, pages: Sequence[int]) -> list[Span]:
        """Routed pages as page ranges: gaps up to DOC_GAP merged, lanes filled, then capped at DOC_SPAN pages."""
        cuts = [index for index, (before, after) in enumerate(pairwise(pages), 1) if after - before - 1 > self._gap]
        runs = [(pages[start], pages[end - 1]) for start, end in pairwise([0, *cuts, len(pages)])] if pages else []
        cap = self._span
        lanes = self._process_lanes(runs)
        return [(start, min(start + cap - 1, last)) for first, last in lanes for start in range(first, last + 1, cap)]

    def _process_lanes(self, runs: list[Span]) -> list[Span]:
        """Halve the longest run while there are fewer runs than DOC_CONCURRENCY lanes and both halves keep LANE
        pages — below that, a second request costs more than the parallelism returns."""
        match max(runs, key=lambda run: run[1] - run[0], default=None):
            case (first, last) as longest if len(runs) < self._concurrency and last - first + 1 >= 2 * LANE:
                middle = first + (last - first + 1) // 2
                return self._process_lanes(
                    sorted([*(run for run in runs if run != longest), (first, middle - 1), (middle, last)])
                )
            case _:
                return runs

    def _process_options(self, span: Span, signals: Signals, elements: frozenset[Element]) -> dict[str, object]:
        """What docling runs on the span, by what its pages showed and what is asked: OCR only for scans, pictures only
        for figures, table structure only for tables."""
        seen = {signal for page in range(span[0], span[1] + 1) for signal in signals.get(page, ())}
        asked = elements if seen & FIGURES else elements - {Element.PICTURES}
        return {
            "page_range": list(span),
            "md_page_break_placeholder": BREAK,
            "do_ocr": DocSignal.SCANNED in seen,
            "table_mode": str(self._tables),
            **self._process_drops(asked),
        }

    @staticmethod
    def _process_drops(elements: frozenset[Element]) -> dict[str, object]:
        """The docling options that switch off what no asked element needs."""
        return {key: value for element, drop in DROPS.items() if element not in elements for key, value in drop.items()}

    async def _process_convert(
        self, raw: bytes, name: str, spans: Sequence[Span], signals: Signals, elements: frozenset[Element]
    ) -> dict[Span, DocumentConversion | str]:
        """Every span through docling, DOC_CONCURRENCY at a time; a span that fails yields its reason, never raises."""
        gate = anyio.Semaphore(self._concurrency)
        outcomes: dict[Span, DocumentConversion | str] = {}

        async def convert(span: Span, port: DocumentPort) -> None:
            async with gate:
                try:
                    options = self._process_options(span, signals, elements)
                    outcomes[span] = await port.convert(raw, filename=name, options=options)
                except FAILURES as error:
                    outcomes[span] = f"{type(error).__name__}: {error}"
                    logger.debug("docling span failed, liteparse reads it", span=span, error=outcomes[span])

        match self._port:
            case None:
                return outcomes
            case port:
                async with anyio.create_task_group() as group:
                    _ = [group.start_soon(convert, span, port) for span in spans]
                return outcomes

    ##### PRIVATE — the PDF, page by page #####

    async def _process_pdf(self, raw: bytes, name: str, elements: frozenset[Element]) -> Document:
        """A PDF: liteparse on every page, docling — when present — on the pages its signals route, one Document out."""
        fast = {page.number: page for page in await self._pages.parse(raw)}
        signals = {number: page.signals for number, page in fast.items()}
        spans = self._process_spans(self._process_route(signals, elements))
        outcomes = await self._process_convert(raw, name, spans, signals, elements)
        owned = {number for first, last in spans for number in range(first, last + 1)}
        spanned = [self._process_span(span, outcomes[span], fast) for span in spans]
        lone = [self._process_fast(page) for number, page in fast.items() if number not in owned]
        document = self._process_document(
            name,
            [*(page for pages, _ in spanned for page in pages), *(page for page, _ in lone)],
            [*(read for _, reads in spanned for read in reads), *(read for _, read in lone)],
        )
        logger.info("document read", name=name, pages=len(fast), deep=len(document.deep), spans=len(spans), step="DOC")
        return document

    def _process_span(
        self, span: Span, outcome: DocumentConversion | str, fast: Mapping[int, FastPage]
    ) -> tuple[list[Page], list[Reading]]:
        """A span's pages and objects: docling's, read once, when the span converted; liteparse's, its failure said,
        when not."""
        numbers = range(span[0], span[1] + 1)
        match outcome:
            case DocumentConversion() as conversion:
                markdown = self._process_breaks(conversion, span)
                pages = [
                    Page(
                        number=number,
                        backend=Backend.DOCLING,
                        signals=fast[number].signals,
                        markdown=markdown.get(number, fast[number].markdown),
                    )
                    for number in numbers
                ]
                return pages, [self._process_deep(conversion, f"docling:{span[0]}-{span[1]}", span)]
            case failure:
                reads = [self._process_fast(fast[number], failure) for number in numbers]
                return [page for page, _ in reads], [read for _, read in reads]

    @classmethod
    def _process_fast(cls, page: FastPage, fallback: str = "") -> tuple[Page, Reading]:
        """A fast page read by liteparse: its text items and tables, in block order, and why docling's did not stand."""
        number = page.number
        blocks = list(enumerate(page.blocks))
        rows: list[Row] = [
            {
                "ref": f"liteparse:p{number}/b{index}",
                "page": number,
                "label": KINDS.get(block.kind, block.kind),
                "text": block.text,
                "level": block.level,
                "backend": Backend.LITEPARSE,
                "group": "",
                "hyperlink": "",
            }
            for index, block in blocks
            if block.kind != TABLE
        ]
        tables = [
            Table(
                ref=f"liteparse:p{number}/b{index}",
                page=number,
                caption="",
                frame=cls._process_frame([list(block.header)] if block.header else [], [list(r) for r in block.rows]),
                backend=Backend.LITEPARSE,
            )
            for index, block in blocks
            if block.kind == TABLE
        ]
        read = Page(
            number=number, backend=Backend.LITEPARSE, signals=page.signals, markdown=page.markdown, fallback=fallback
        )
        return read, Reading(rows, tables, [], [])

    @staticmethod
    def _process_breaks(conversion: DocumentConversion, span: Span) -> dict[int, str]:
        """The span's markdown split back into its pages, when docling wrote one break per page — none when it wrote
        nothing — every embedded picture left as a marker."""
        text = EMBEDDED.sub(IMAGE, conversion.markdown)
        parts = [part.strip() for part in text.split(BREAK)] if text.strip() else []
        pages = range(span[0], span[1] + 1)
        return dict(zip(pages, parts, strict=True)) if len(parts) == len(pages) else {}

    ##### PRIVATE — docling's document, read once #####

    @classmethod
    def _process_deep(cls, conversion: DocumentConversion, prefix: str, span: Span | None) -> Reading:
        """A docling conversion's objects, each placed on its page in one pass — off the span or unplaced, dropped —,
        their refs under `prefix`."""
        document = conversion.document
        texts = [(node, page) for node in document.get("texts") or () if (page := cls._process_place(node, span))]
        tables = [(node, page) for node in document.get("tables") or () if (page := cls._process_place(node, span))]
        pictures = [(node, page) for node in document.get("pictures") or () if (page := cls._process_place(node, span))]
        return Reading(
            rows=[
                cls._process_item(document, node, prefix, page)
                for node, page in texts
                if node.get("content_layer", "body") == "body"
            ],
            tables=[cls._process_table(document, node, prefix, page) for node, page in tables],
            pictures=[cls._process_picture(document, node, prefix, page) for node, page in pictures],
            formulas=[
                Formula(ref=f"{prefix}{node['self_ref']}", page=page, text=node.get("text", ""))
                for node, page in texts
                if node["label"] == "formula"
            ],
        )

    @staticmethod
    def _process_place(node: Node, span: Span | None) -> int:
        """The page a node is placed on: 1 for a whole document's; for a span's, the page it starts on — 0 off the span
        or when docling gave it no provenance."""
        page = next((prov["page_no"] for prov in node.get("prov") or ()), 0)
        match span:
            case None:
                return 1
            case _:
                return page if span[0] <= page <= span[1] else 0

    @staticmethod
    def _process_item(document: Node, node: Node, prefix: str, page: int) -> Row:
        """A docling text node as an item, with the label of the group it sits in (`list`, `slide`…; empty in the
        body)."""
        match (node.get("parent") or {}).get("$ref", "").split("/"):
            case ["#", "groups", index]:
                group = document["groups"][int(index)].get("label", "")
            case _:
                group = ""
        return {
            "ref": f"{prefix}{node['self_ref']}",
            "page": page,
            "label": node["label"],
            "text": node.get("text", ""),
            "level": node.get("level"),
            "backend": Backend.DOCLING,
            "group": group,
            "hyperlink": str(node.get("hyperlink") or ""),
        }

    @classmethod
    def _process_table(cls, document: Node, node: Node, prefix: str, page: int) -> Table:
        """A docling table: its grid as a frame, leading all-header rows as the column names."""
        grid = node["data"].get("grid") or []
        rows = [[cell.get("text", "") for cell in row] for row in grid]
        heads = sum(1 for _ in takewhile(lambda row: all(cell.get("column_header") for cell in row), grid))
        return Table(
            ref=f"{prefix}{node['self_ref']}",
            page=page,
            caption=cls._process_caption(document, node),
            frame=cls._process_frame(rows[:heads], rows[heads:]),
            backend=Backend.DOCLING,
        )

    @classmethod
    def _process_picture(cls, document: Node, node: Node, prefix: str, page: int) -> Picture:
        """A docling picture: its bytes when embedded (none for a placeholder), its size, the classifier's classes most
        likely first (none unless classification ran)."""
        image = node.get("image") or {}
        uri, size = image.get("uri") or "", image.get("size") or {}
        head, _, payload = uri.partition(",")
        predicted = [
            prediction
            for annotation in node.get("annotations") or ()
            if annotation.get("kind") == "classification"
            for prediction in annotation.get("predicted_classes") or ()
        ]
        return Picture(
            ref=f"{prefix}{node['self_ref']}",
            page=page,
            caption=cls._process_caption(document, node),
            mimetype=image.get("mimetype", ""),
            data=base64.b64decode(payload) if head.endswith(";base64") else b"",
            width=int(size.get("width", 0)),
            height=int(size.get("height", 0)),
            classes=tuple(p["class_name"] for p in sorted(predicted, key=lambda p: -p.get("confidence", 0.0))),
        )

    @staticmethod
    def _process_caption(document: Node, node: Node) -> str:
        """A node's captions, resolved through their JSON pointers (`#/texts/80`) by index."""
        refs = (caption["$ref"].split("/") for caption in node.get("captions") or ())
        return " ".join(document[collection][int(index)]["text"] for _, collection, index in refs)

    @staticmethod
    def _process_frame(heads: Sequence[Sequence[str]], body: Sequence[Sequence[str]]) -> pl.DataFrame:
        """Header rows folded into unique column names (a spanning cell's text once per column), the body as text."""
        width = max((len(row) for row in (*heads, *body)), default=0)
        titles = [
            " ".join(dict.fromkeys(filter(None, (row[c] for row in heads if c < len(row))))) or f"column_{c}"
            for c in range(width)
        ]
        names = [
            f"{title}_{titles[:c].count(title)}" if title in titles[:c] else title for c, title in enumerate(titles)
        ]
        padded = [[*row, *[""] * (width - len(row))] for row in body]
        return pl.DataFrame(padded, schema=dict.fromkeys(names, pl.String()), orient="row")

    ##### PRIVATE — any other document, whole #####

    async def _process_whole(self, raw: bytes, name: str, fmt: str, elements: frozenset[Element]) -> Document:
        """A non-PDF, whole: docling when it is present, asked and reads the format; anytomd otherwise, and in docling's
        place when docling fails on it."""
        asked = self._port if self._mode is not DocMode.LITE and fmt in WHOLE else None
        match asked:
            case None:
                return await self._process_anytomd(raw, name, fmt)
            case port:
                try:
                    conversion = await port.convert(raw, filename=name, options=self._process_drops(elements))
                except FAILURES as error:
                    reason = f"{type(error).__name__}: {error}"
                    logger.debug("docling document failed, anytomd reads it", name=name, error=reason)
                    return await self._process_anytomd(raw, name, fmt, fallback=reason)
                page = Page(
                    number=1, backend=Backend.DOCLING, signals=(), markdown=EMBEDDED.sub(IMAGE, conversion.markdown)
                )
                return self._process_document(name, [page], [self._process_deep(conversion, "docling:", None)])

    async def _process_anytomd(self, raw: bytes, name: str, fmt: str, *, fallback: str = "") -> Document:
        """anytomd's reading of a whole document: one page, its Markdown cut into heading and text items.

        The engine wants the concrete extension — the name's own suffix when it has one, else the detected format."""
        extension = PurePath(name).suffix.lstrip(".").lower() or fmt
        conversion = await self._md.convert(raw, extension=extension)
        page = Page(number=1, backend=Backend.ANYTOMD, signals=(), markdown=conversion.markdown, fallback=fallback)
        reading = Reading(self._process_blocks(conversion.markdown), [], [], [])
        return self._process_document(name, [page], [reading], conversion.warnings)

    @staticmethod
    def _process_blocks(markdown: str) -> list[Row]:
        """Markdown blocks as items: a heading keeps its level, any other block is text."""
        blocks = [block.strip() for block in BLOCKS.split(markdown) if block.strip()]
        return [
            {
                "ref": f"anytomd:b{index}",
                "page": 1,
                "label": "section_header" if (heading := HEADING.match(block)) else "text",
                "text": heading.group(2).strip() if heading else block,
                "level": len(heading.group(1)) if heading else None,
                "backend": Backend.ANYTOMD,
                "group": "",
                "hyperlink": "",
            }
            for index, block in enumerate(blocks)
        ]

    ##### PRIVATE — the document #####

    @staticmethod
    def _process_document(
        name: str, pages: Iterable[Page], readings: Sequence[Reading], warnings: tuple[str, ...] = ()
    ) -> Document:
        """The readings as one Document in page order — a stable sort, each engine's own order kept within a page."""
        page = attrgetter("page")
        return Document(
            name=name,
            pages=tuple(sorted(pages, key=attrgetter("number"))),
            items=pl.DataFrame([row for read in readings for row in read.rows], schema=ITEMS).sort(
                "page", maintain_order=True
            ),
            tables=tuple(sorted(chain.from_iterable(read.tables for read in readings), key=page)),
            pictures=tuple(sorted(chain.from_iterable(read.pictures for read in readings), key=page)),
            formulas=tuple(sorted(chain.from_iterable(read.formulas for read in readings), key=page)),
            warnings=warnings,
        )

    ############################################################

    ##### PUBLIC #####

    async def process(self, source: bytes | Path, *, name: str = "", elements: frozenset[Element] = EVERY) -> Document:
        """Read one document — the `elements` asked, every one by default —, refused before any engine when too big or
        of no format a reader takes."""
        name = name or (getattr(source, "name", "") or "document")
        raw = await self._process_read(source, name)
        logger.debug("doc process", name=name, size=len(raw), mode=str(self._mode), deep=self._port is not None)
        match self._md.detect(name, raw):
            case None | "zip":
                msg = f"{name!r} is not one document of a format a reader takes"
                raise UnsupportedFormatError(msg)
            case "pdf":
                return await self._process_pdf(raw, name, elements)
            case fmt:
                return await self._process_whole(raw, name, fmt, elements)

    async def text(self, source: bytes | Path, *, name: str = "") -> str:
        """The document as markdown, docling asked only for the scans."""
        return (await self.process(source, name=name, elements=frozenset({Element.TEXT}))).markdown

    async def tables(self, source: bytes | Path, *, name: str = "") -> tuple[Table, ...]:
        """The document's tables, docling asked only for table pages and scans, no picture exported."""
        return (await self.process(source, name=name, elements=frozenset({Element.TABLES}))).tables

    async def pictures(self, source: bytes | Path, *, name: str = "") -> tuple[Picture, ...]:
        """The document's pictures — docling's alone, on its figure pages, no table structure run."""
        return (await self.process(source, name=name, elements=frozenset({Element.PICTURES}))).pictures

    async def formulas(self, source: bytes | Path, *, name: str = "") -> tuple[Formula, ...]:
        """The document's formulas — docling's alone, on every routed page, no table structure or picture run."""
        return (await self.process(source, name=name, elements=frozenset({Element.FORMULAS}))).formulas

    async def sections(self, source: bytes | Path, *, name: str = "") -> list[Section]:
        """Every heading with the body text under it, read as `text` reads."""
        return (await self.process(source, name=name, elements=frozenset({Element.TEXT}))).sections
