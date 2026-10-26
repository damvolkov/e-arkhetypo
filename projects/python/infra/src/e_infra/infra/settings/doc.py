"""infra/settings/doc: the document processor — which engine reads which page, and how hard to push the deep one (DOC_*)."""

from enum import StrEnum, auto
from pathlib import Path

from pydantic import Field

from e_infra.infra.settings.base import BaseSettings
from e_infra.infra.settings.docling import DoclingTables


##### ENUMS #####
class DocMode(StrEnum):
    """Who reads a document: liteparse alone (`lite`), docling alone (`deep`), or each page by its signals (`hybrid`)."""

    LITE = auto()
    DEEP = auto()
    HYBRID = auto()


class DocSignal(StrEnum):
    """What liteparse sees on a page, in its fast pass, that sends the page to docling in hybrid mode.

    `table` — a table block or table-like layout (TableFormer reads structure liteparse may fuse or split);
    `graphics` — figures or dense vector graphics (docling crops, captions and classifies pictures);
    `scanned` — no usable text layer: a scan, vector-drawn or garbled text (docling's OCR keeps tables);
    `images` — embedded raster images beside the text; `columns` — more than one text column."""

    TABLE = auto()
    GRAPHICS = auto()
    SCANNED = auto()
    IMAGES = auto()
    COLUMNS = auto()


##### SETTINGS #####
class DocSettings(BaseSettings):
    """DOC_MODE — lite | deep | hybrid; DOC_ROUTE — the signals that send a page to docling (JSON list);
    DOC_GAP — pages between two docling spans merged into one request (a request costs more than a page);
    DOC_SPAN — most pages one docling request carries (more spans run in parallel when the server has the
    workers); DOC_CONCURRENCY — docling requests in flight; DOC_TABLES — TableFormer's mode on routed pages; DOC_OCR / DOC_TESSDATA / DOC_OCR_LANGUAGE —
    liteparse's own Tesseract, for scanned pages docling does not take (lite mode, or docling down);
    DOC_WORKERS — liteparse's page workers (0: its default). Defaults measured on the 10-K corpus, 2026-10-13."""

    doc_mode: DocMode = DocMode.HYBRID
    doc_route: tuple[DocSignal, ...] = (DocSignal.TABLE, DocSignal.GRAPHICS, DocSignal.SCANNED, DocSignal.IMAGES)
    doc_gap: int = Field(default=1, ge=0)
    doc_span: int = Field(default=64, ge=1)
    doc_concurrency: int = Field(default=2, ge=1)
    doc_tables: DoclingTables = DoclingTables.ACCURATE
    doc_ocr: bool = False
    doc_tessdata: Path | None = None
    doc_ocr_language: str = "eng"
    doc_workers: int = Field(default=0, ge=0)
