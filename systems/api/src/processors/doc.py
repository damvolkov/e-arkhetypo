"""processors/doc: the DocProcessor — every page read by the engine that reads it best, as fast as the pair allows.

Hybrid by measurement (10-K and paper corpus, 2026-10-13). liteparse (Rust, in-process) reads a whole
filing in under a second and matches docling on running text — 98.7% of docling's words — but not on
tables: rows fused or split on ~4 in 10 table pages, captions and formulas absent. docling-serve reads
tables with TableFormer, crops and classifies pictures, OCRs scans keeping their tables, at ~1-1.7 s a
page plus ~1.8 s a request. No signal liteparse computes *before* parsing predicts which of its tables
are wrong; what it does tell, almost free, is which pages *hold* tables, figures or scans. So:

1. liteparse reads every page (`aparse`, off the loop) and reports its signals per page;
2. the pages whose signals are in DOC_ROUTE go to docling — the rest keep liteparse's reading;
3. routed pages become spans: neighbours closer than DOC_GAP pages merge (a request costs more than the
   pages between); a long run halves into DOC_CONCURRENCY lanes when each half still pays off (`LANE`);
4. each span asks docling only for what its pages need — OCR for scans, pictures for figures, TableFormer in
   DOC_TABLES mode — and spans convert concurrently, bounded; a failed span falls back to liteparse, said so.

The processor holds the document port (docling) and its own liteparse parser — singletons both — and no
state per document: `process` returns a `Document` whose objects are engine-neutral."""

import base64
import re
from itertools import pairwise, takewhile
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

import anyio
import polars as pl
from liteparse import LiteParse

from adapters.ports import DocumentConversion
from core.logger import logger
from core.settings import settings as st
from core.settings.doc import DocMode, DocSignal
from processors.models import Backend, Document, Formula, Page, Picture, Section, Table

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from liteparse import ParsedPage, ParseResult

    from adapters.ports import DocumentPort
    from core.settings.doc import DocSettings

type Node = dict[str, Any]
type Span = tuple[int, int]
type Rows = list[dict[str, Any]]

### pages a lane must keep for a second request to pay off: measured ~1.8 s a request, ~1.7 s a routed page, x1.35 from
### two in flight (docling-serve CPU, 2026-10-13) — a run splits in two only when each half keeps at least this many.
LANE: Final[int] = 2
### the break docling writes between pages in markdown: it splits a span's markdown back into its pages.
BREAK: Final[str] = "<!-- page-break -->"
### a picture embedded in markdown is bytes in a text: the bytes live in `Document.pictures`, the text keeps a marker.
EMBEDDED: Final[re.Pattern[str]] = re.compile(r"!\[[^\]]*\]\(data:[^)]*\)")
IMAGE: Final[str] = "<!-- image -->"
HEADINGS: Final[frozenset[str]] = frozenset({"title", "section_header"})
BODY: Final[frozenset[str]] = frozenset({"text", "list_item", "paragraph"})
### liteparse block kinds onto docling's labels; a `rule` (a drawn line) carries no text and is dropped.
KINDS: Final[Mapping[str, str]] = MappingProxyType(
    {"heading": "section_header", "paragraph": "text", "list_item": "list_item"}
)
SCANNED: Final[frozenset[str]] = frozenset({"scanned", "vector-text", "garbled"})
ITEMS: Final[Mapping[str, pl.DataType]] = MappingProxyType(
    {
        "ref": pl.String(),
        "page": pl.Int64(),
        "label": pl.String(),
        "text": pl.String(),
        "level": pl.Int64(),
        "backend": pl.String(),
    }
)


class DocProcessor:
    """Reads documents page by page: liteparse everywhere, docling where the page's signals ask for it."""

    __slots__ = ("_conf", "_parser", "_port")

    def __init__(self, port: DocumentPort, settings: DocSettings | None = None) -> None:
        ### the default is read on call, not at import: the settings singleton stays lazy.
        self._conf = st.doc if settings is None else settings
        self._port = port
        tessdata = self._conf.doc_tessdata
        self._parser = LiteParse(
            ocr_enabled=self._conf.doc_ocr,
            tessdata_path=str(tessdata) if tessdata is not None else None,
            ocr_language=self._conf.doc_ocr_language,
            num_workers=self._conf.doc_workers or None,
            extract_blocks=True,
            include_complexity=True,
            output_format="markdown",
            quiet=True,
        )

    ##### PRIVATE — routing #####

    @staticmethod
    def _process_signals(page: ParsedPage) -> tuple[DocSignal, ...]:
        """What liteparse's fast pass saw on the page that docling reads better, in DocSignal order."""
        stats = page.complexity
        layout = stats.layout if stats is not None else None
        reasons = set(stats.reasons) if stats is not None else set()
        shapes = set(layout.reasons) if layout is not None else set()
        seen = {
            DocSignal.TABLE: any(block.kind == "table" for block in page.blocks or ())
            or "table-likely" in shapes
            or bool(layout is not None and layout.text_table_run_count),
            DocSignal.GRAPHICS: "dense-graphics" in shapes or bool(layout is not None and layout.figure_count),
            ### `no-text` alone is a blank page; only with an image under it is it a scan.
            DocSignal.SCANNED: bool(reasons & SCANNED)
            or ("no-text" in reasons and bool(stats.full_page_image or stats.has_substantial_images)),
            DocSignal.IMAGES: "embedded-images" in reasons,
            DocSignal.COLUMNS: "multi-column" in shapes,
        }
        return tuple(signal for signal in DocSignal if seen[signal])

    def _process_route(self, signals: Mapping[int, tuple[DocSignal, ...]]) -> list[int]:
        """The pages docling reads, ascending: none, all, or those whose signals DOC_ROUTE names."""
        route = set(self._conf.doc_route)
        match self._conf.doc_mode:
            case DocMode.LITE:
                return []
            case DocMode.DEEP:
                return sorted(signals)
            case _:
                return sorted(page for page, seen in signals.items() if route & set(seen))

    def _process_spans(self, pages: Sequence[int]) -> list[Span]:
        """Routed pages as page ranges: gaps up to DOC_GAP merged, lanes filled, then capped at DOC_SPAN pages."""
        starts = [pages[0]] if pages else []
        starts += [after for before, after in pairwise(pages) if after - before - 1 > self._conf.doc_gap]
        ends = [before for before, after in pairwise(pages) if after - before - 1 > self._conf.doc_gap]
        runs = self._spans_lanes(list(zip(starts, [*ends, pages[-1]] if pages else [], strict=True)))
        cap = self._conf.doc_span
        return [(start, min(start + cap - 1, last)) for first, last in runs for start in range(first, last + 1, cap)]

    def _spans_lanes(self, runs: list[Span]) -> list[Span]:
        """Halve the longest run while there are fewer runs than DOC_CONCURRENCY lanes and both halves keep LANE
        pages — below that, a second request costs more than the parallelism returns."""
        longest = max(runs, key=lambda run: run[1] - run[0], default=None)
        match longest:
            case (first, last) if len(runs) < self._conf.doc_concurrency and last - first + 1 >= 2 * LANE:
                middle = first + (last - first + 1) // 2
                split = [run for run in runs if run != longest] + [(first, middle - 1), (middle, last)]
                return self._spans_lanes(sorted(split))
            case _:
                return runs

    def _process_options(self, span: Span, signals: Mapping[int, tuple[DocSignal, ...]]) -> dict[str, object]:
        """What docling runs on the span, by what its pages showed: OCR only for scans, pictures only for figures."""
        seen = {signal for page in range(span[0], span[1] + 1) for signal in signals.get(page, ())}
        pictures = bool(seen & {DocSignal.GRAPHICS, DocSignal.IMAGES})
        return {
            "page_range": list(span),
            "md_page_break_placeholder": BREAK,
            "do_ocr": DocSignal.SCANNED in seen,
            "table_mode": str(self._conf.doc_tables),
            **({} if pictures else {"image_export_mode": "placeholder", "include_images": False}),
        }

    async def _process_deep(
        self, raw: bytes, name: str, spans: Sequence[Span], signals: Mapping[int, tuple[DocSignal, ...]]
    ) -> dict[Span, DocumentConversion | str]:
        """Every span through docling, DOC_CONCURRENCY at a time; a span that fails yields its reason, never raises."""
        gate = anyio.Semaphore(self._conf.doc_concurrency)
        outcomes: dict[Span, DocumentConversion | str] = {}

        async def convert(span: Span) -> None:
            async with gate:
                try:
                    options = self._process_options(span, signals)
                    outcomes[span] = await self._port.convert(raw, filename=name, options=options)
                except Exception as error:  # noqa: BLE001 — a failed span falls back to liteparse, its reason kept
                    outcomes[span] = f"{type(error).__name__}: {error}"
                    logger.warning("docling span failed", span=span, error=outcomes[span], step="DOC")

        async with anyio.create_task_group() as group:
            _ = [group.start_soon(convert, span) for span in spans]
        return outcomes

    ##### PRIVATE — liteparse pages #####

    @classmethod
    def _lite_read(cls, page: ParsedPage, number: int) -> tuple[Rows, list[Table]]:
        """A liteparse page's text items and tables, in block order."""
        blocks = list(enumerate(page.blocks or ()))
        rows = [
            {
                "ref": f"liteparse:p{number}/b{index}",
                "page": number,
                "label": KINDS[block.kind],
                "text": block.text or "",
                "level": block.level if block.kind == "heading" else None,
                "backend": Backend.LITEPARSE,
            }
            for index, block in blocks
            if block.kind in KINDS
        ]
        tables = [
            Table(
                ref=f"liteparse:p{number}/b{index}",
                page=number,
                caption="",
                frame=cls._common_frame(
                    [[cell.text or "" for cell in block.header]] if block.header else [],
                    [[cell.text or "" for cell in row] for row in block.rows or ()],
                ),
                backend=Backend.LITEPARSE,
            )
            for index, block in blocks
            if block.kind == "table"
        ]
        return rows, tables

    ##### PRIVATE — docling pages #####

    @classmethod
    def _deep_read(
        cls, conversion: DocumentConversion, span: Span, number: int
    ) -> tuple[Rows, list[Table], list[Picture], list[Formula]]:
        """A docling span's objects that start on page `number`."""
        document, prefix = conversion.document, f"docling:{span[0]}-{span[1]}"
        on_page = lambda node: cls._common_page(node) == number  # noqa: E731 — one predicate, four reads
        texts = [node for node in document.get("texts") or () if on_page(node)]
        rows = [
            {
                "ref": f"{prefix}{node['self_ref']}",
                "page": number,
                "label": node["label"],
                "text": node.get("text", ""),
                "level": node.get("level"),
                "backend": Backend.DOCLING,
            }
            for node in texts
            if node.get("content_layer", "body") == "body"
        ]
        tables = [
            Table(
                ref=f"{prefix}{node['self_ref']}",
                page=number,
                caption=cls._common_caption(document, node),
                frame=cls._deep_frame(node["data"].get("grid") or []),
                backend=Backend.DOCLING,
            )
            for node in document.get("tables") or ()
            if on_page(node)
        ]
        pictures = [
            Picture(
                ref=f"{prefix}{node['self_ref']}",
                page=number,
                caption=cls._common_caption(document, node),
                classes=cls._deep_classes(node),
                **cls._deep_image(node),
            )
            for node in document.get("pictures") or ()
            if on_page(node)
        ]
        formulas = [
            Formula(ref=f"{prefix}{node['self_ref']}", page=number, text=node.get("text", ""))
            for node in texts
            if node["label"] == "formula"
        ]
        return rows, tables, pictures, formulas

    @staticmethod
    def _deep_markdown(conversion: DocumentConversion, span: Span) -> dict[int, str]:
        """The span's markdown split back into its pages, when docling wrote one break per page — none when it wrote
        nothing — every embedded picture left as a marker: its bytes are the document's pictures, never its text."""
        text = EMBEDDED.sub(IMAGE, conversion.markdown)
        parts = [part.strip() for part in text.split(BREAK)] if text.strip() else []
        pages = range(span[0], span[1] + 1)
        return dict(zip(pages, parts, strict=True)) if len(parts) == len(pages) else {}

    @classmethod
    def _deep_frame(cls, grid: Sequence[Sequence[Node]]) -> pl.DataFrame:
        """A docling grid as a frame: leading all-header rows become the column names."""
        rows = [[cell.get("text", "") for cell in row] for row in grid]
        heads = sum(1 for _ in takewhile(lambda row: all(cell.get("column_header") for cell in row), grid))
        return cls._common_frame(rows[:heads], rows[heads:])

    @staticmethod
    def _deep_image(node: Node) -> dict[str, Any]:
        """The picture's image fields — mimetype, bytes, width, height — empty for a placeholder."""
        image = node.get("image") or {}
        uri, size = image.get("uri") or "", image.get("size") or {}
        head, _, payload = uri.partition(",")
        return {
            "mimetype": image.get("mimetype", ""),
            "data": base64.b64decode(payload) if head.endswith(";base64") else b"",
            "width": int(size.get("width", 0)),
            "height": int(size.get("height", 0)),
        }

    @staticmethod
    def _deep_classes(node: Node) -> tuple[str, ...]:
        """The picture classifier's classes, most likely first; none unless classification ran."""
        predicted = [
            prediction
            for annotation in node.get("annotations") or ()
            if annotation.get("kind") == "classification"
            for prediction in annotation.get("predicted_classes") or ()
        ]
        return tuple(item["class_name"] for item in sorted(predicted, key=lambda item: -item.get("confidence", 0.0)))

    ##### PRIVATE — shared #####

    @staticmethod
    def _common_frame(heads: Sequence[Sequence[str]], body: Sequence[Sequence[str]]) -> pl.DataFrame:
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

    @staticmethod
    def _common_page(node: Node) -> int:
        """The page a node starts on; 0 when docling gave it no provenance."""
        return next((prov["page_no"] for prov in node.get("prov") or ()), 0)

    @staticmethod
    def _common_caption(document: Node, node: Node) -> str:
        """A node's captions, resolved through their JSON pointers (`#/texts/80`) by index."""
        refs = (caption["$ref"].split("/") for caption in node.get("captions") or ())
        return " ".join(document[collection][int(index)]["text"] for _, collection, index in refs)

    ############################################################

    ##### PUBLIC #####

    async def process(self, source: bytes | Path, *, name: str = "") -> Document:
        """Read a document: liteparse on every page, docling on the pages its signals route, one Document out."""
        raw = source if isinstance(source, bytes) else await anyio.Path(source).read_bytes()
        name = name or (getattr(source, "name", "") or "document.pdf")
        lite: ParseResult = await self._parser.aparse(raw)
        numbers = range(1, lite.num_pages + 1)
        pages = {number: lite.get_page(number) for number in numbers}
        signals = {number: self._process_signals(page) for number, page in pages.items()}
        spans = self._process_spans(self._process_route(signals))
        outcomes = await self._process_deep(raw, name, spans, signals)
        owner = {number: span for span in spans for number in range(span[0], span[1] + 1)}
        owned = {number: (span, outcomes[span]) for number, span in owner.items()}
        reads = [self._process_page(pages[number], number, signals[number], owned.get(number)) for number in numbers]
        logger.info(
            "document read",
            name=name,
            pages=len(reads),
            deep=sum(read[0].backend is Backend.DOCLING for read in reads),
            spans=len(spans),
            step="DOC",
        )
        return Document(
            name=name,
            pages=tuple(read[0] for read in reads),
            items=pl.DataFrame([row for read in reads for row in read[1]], schema=ITEMS),
            tables=tuple(table for read in reads for table in read[2]),
            pictures=tuple(picture for read in reads for picture in read[3]),
            formulas=tuple(formula for read in reads for formula in read[4]),
        )

    def _process_page(
        self,
        page: ParsedPage,
        number: int,
        signals: tuple[DocSignal, ...],
        owned: tuple[Span, DocumentConversion | str] | None,
    ) -> tuple[Page, Rows, list[Table], list[Picture], list[Formula]]:
        """One page from the engine that owns it: its docling span when the span converted, liteparse otherwise."""
        match owned:
            case (span, DocumentConversion() as conversion):
                rows, tables, pictures, formulas = self._deep_read(conversion, span, number)
                markdown = self._deep_markdown(conversion, span).get(number, page.markdown or "")
                read = Page(number=number, backend=Backend.DOCLING, signals=signals, markdown=markdown)
                return read, rows, tables, pictures, formulas
            case (_, str() as failure):
                rows, tables = self._lite_read(page, number)
                read = Page(
                    number=number,
                    backend=Backend.LITEPARSE,
                    signals=signals,
                    markdown=page.markdown or "",
                    fallback=failure,
                )
                return read, rows, tables, [], []
            case _:
                rows, tables = self._lite_read(page, number)
                read = Page(number=number, backend=Backend.LITEPARSE, signals=signals, markdown=page.markdown or "")
                return read, rows, tables, [], []

    @staticmethod
    def sections(document: Document) -> list[Section]:
        """Every heading with the body text under it, up to the next heading — one pass over the items frame.

        Text before the first heading belongs to no section and is left out."""
        frame = (
            document.items.with_columns(section=pl.col("label").is_in(HEADINGS).cum_sum())
            .filter(pl.col("section") > 0)
            .group_by("section", maintain_order=True)
            .agg(
                ref=pl.col("ref").first(),
                title=pl.col("text").first(),
                level=pl.col("level").first().fill_null(1),
                page=pl.col("page").first(),
                text=pl.col("text").filter(pl.col("label").is_in(BODY)).str.join("\n"),
            )
        )
        return [Section(**row) for row in frame.drop("section").iter_rows(named=True)]
