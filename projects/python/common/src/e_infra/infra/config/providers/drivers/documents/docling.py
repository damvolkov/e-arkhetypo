"""infra/config/providers/drivers/documents/docling: the docling-serve edge — where it lives and how it converts."""

from datetime import timedelta
from enum import StrEnum, auto

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from e_infra.infra.config.base import BaseSettings


##### ENUMS #####
class DoclingFormat(StrEnum):
    """What a conversion hands back: markdown, the lossless DoclingDocument JSON, html, plain text, doctags."""

    MD = auto()
    JSON = auto()
    HTML = auto()
    TEXT = auto()
    DOCTAGS = auto()


class DoclingImages(StrEnum):
    """How pictures come back: a placeholder only, embedded as base64 data URIs, or referenced by path."""

    PLACEHOLDER = auto()
    EMBEDDED = auto()
    REFERENCED = auto()


class DoclingTables(StrEnum):
    """TableFormer's mode: `accurate` recovers merged cells and headers, `fast` trades that for speed."""

    FAST = auto()
    ACCURATE = auto()


class DoclingBackend(StrEnum):
    """The PDF parser: docling's own (layout-faithful) or pypdfium2 (lighter, plainer)."""

    DOCLING_PARSE = auto()
    PYPDFIUM2 = auto()


##### SETTINGS #####
class DoclingSettings(BaseSettings):
    """DOCLING_URL — the docling-serve base; DOCLING_TIMEOUT — each HTTP call; DOCLING_DEADLINE — a whole conversion,
    polls included; DOCLING_POLL — the pause between two status polls of a running conversion; DOCLING_FORMATS —
    outputs asked (JSON list); DOCLING_IMAGES — picture export; DOCLING_IMAGES_SCALE — picture resolution;
    DOCLING_TABLES — TableFormer mode; DOCLING_OCR / DOCLING_FORCE_OCR / DOCLING_OCR_ENGINE / DOCLING_OCR_LANG — OCR
    (forced: every page rasterized, scans and text alike); DOCLING_BACKEND — PDF parser; DOCLING_FORMULAS /
    DOCLING_PICTURES / DOCLING_CHARTS / DOCLING_CODE — enrichment models (LaTeX formulas, picture classes, chart data,
    code language); DOCLING_PAGE_TIMEOUT — the server's own per-document deadline, unset for none."""

    model_config = SettingsConfigDict(env_prefix="DOCLING_")

    url: str = "http://localhost:45800"
    timeout: timedelta = timedelta(seconds=60)
    deadline: timedelta = timedelta(minutes=15)
    poll: timedelta = timedelta(seconds=1)
    page_timeout: timedelta | None = None
    formats: tuple[DoclingFormat, ...] = (DoclingFormat.MD, DoclingFormat.JSON)
    images: DoclingImages = DoclingImages.EMBEDDED
    images_scale: float = Field(default=2.0, gt=0.0)
    tables: DoclingTables = DoclingTables.ACCURATE
    ocr: bool = True
    force_ocr: bool = False
    ocr_engine: str = "auto"
    ocr_lang: tuple[str, ...] = ()
    backend: DoclingBackend = DoclingBackend.DOCLING_PARSE
    formulas: bool = False
    pictures: bool = False
    charts: bool = False
    code: bool = False
