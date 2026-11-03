"""infra/config/processors/doc: the document processor — which engine reads which page, and how hard to push (DOC_*)."""

from enum import StrEnum, auto

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from e_infra.infra.config.base import BaseSettings
from e_infra.infra.config.providers.drivers.documents.docling import DoclingTables


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
    """DOC_MODE — lite | deep | hybrid; DOC_ROUTE — the signals that send a page to docling (JSON list); DOC_GAP — pages
    between two docling spans merged into one request (a request costs more than a page); DOC_SPAN — most pages one
    docling request carries (more spans run in parallel when the server has the workers); DOC_CONCURRENCY — docling
    requests in flight; DOC_TABLES — TableFormer's mode on routed pages. Defaults measured on the 10-K corpus,
    2026-10-13."""

    model_config = SettingsConfigDict(env_prefix="DOC_")

    concurrency: int = Field(default=2, ge=1)
    span: int = Field(default=64, ge=1)
    gap: int = Field(default=1, ge=0)
    mode: DocMode = DocMode.HYBRID
    route: tuple[DocSignal, ...] = (DocSignal.TABLE, DocSignal.GRAPHICS, DocSignal.SCANNED, DocSignal.IMAGES)
    tables: DoclingTables = DoclingTables.ACCURATE
