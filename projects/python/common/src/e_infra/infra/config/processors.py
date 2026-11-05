"""infra/config/processors: the processors' knobs — a block per processor."""

from enum import StrEnum, auto
from typing import Annotated

from pydantic import ByteSize, Field, NonNegativeInt, PositiveInt

from e_infra.infra.config.base import BaseSettings
from e_infra.infra.config.providers import DoclingTables


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
class ProcessorSettings(BaseSettings):
    """The processors: how a document is read, page by page, and how hard to push. Defaults measured on the 10-K corpus,
    2026-10-13."""

    ### DOC
    ### docling requests in flight; more spans run in parallel when the server has the workers.
    DOC_CONCURRENCY: PositiveInt = 2
    ### most pages one docling request carries.
    DOC_SPAN: PositiveInt = 64
    ### pages between two docling spans merged into one request: a request costs more than a page.
    DOC_GAP: NonNegativeInt = 1
    DOC_MODE: DocMode = DocMode.HYBRID
    ### the signals that send a page to docling.
    DOC_ROUTE: tuple[DocSignal, ...] = (DocSignal.TABLE, DocSignal.GRAPHICS, DocSignal.SCANNED, DocSignal.IMAGES)
    DOC_TABLES: DoclingTables = DoclingTables.ACCURATE
    ### a document over this is refused before any engine reads it.
    DOC_MAX_INPUT_BYTES: Annotated[ByteSize, Field(ge=1)] = ByteSize(100 * 1024 * 1024)
