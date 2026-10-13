"""processors/models: what the processors hand out — a document read, engine-neutral, typed.

Interior data built by code: frozen, slotted dataclasses, never a boundary model. Whoever read a page
(liteparse or docling, see `Page.backend`), its objects look the same: every one keeps its `ref` — the
engine and its own pointer (`docling:110-119#/tables/3`, `liteparse:p44/b7`) — and the `page` it sits
on, so anything extracted from it traces back to where it was read. Labels follow docling's vocabulary
(`section_header`, `text`, `list_item`, `formula`, ...): liteparse blocks are mapped onto it."""

from dataclasses import dataclass
from enum import StrEnum, auto
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import polars as pl

    from core.settings.doc import DocSignal


class Backend(StrEnum):
    """The engine that read a page."""

    LITEPARSE = auto()
    DOCLING = auto()


@dataclass(frozen=True, slots=True)
class Page:
    """One page: who read it, the signals that decided it, its markdown — and, when docling was asked and
    failed, why liteparse's reading stands instead (`fallback`)."""

    number: int
    backend: Backend
    signals: tuple[DocSignal, ...]
    markdown: str
    fallback: str = ""


@dataclass(frozen=True, slots=True)
class Table:
    """One table: its body as a frame of text cells (header rows folded into unique column names)."""

    ref: str
    page: int
    caption: str
    frame: pl.DataFrame
    backend: Backend

    @property
    def shape(self) -> tuple[int, int]:
        """(rows, columns) of the body."""
        return self.frame.shape


@dataclass(frozen=True, slots=True)
class Picture:
    """One picture: its bytes when embedded (empty otherwise), caption, size in pixels, classes most likely first."""

    ref: str
    page: int
    caption: str
    mimetype: str
    data: bytes
    width: int
    height: int
    classes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Formula:
    """One formula as read: LaTeX when docling's formula enrichment ran, the PDF's own glyphs otherwise."""

    ref: str
    page: int
    text: str


@dataclass(frozen=True, slots=True)
class Section:
    """One heading with the body text under it, up to the next heading."""

    ref: str
    title: str
    level: int
    page: int
    text: str


@dataclass(frozen=True, slots=True)
class Document:
    """A document read page by page: the pages, every text item as one frame in reading order (ref, page,
    label, text, level, backend), and the tables, pictures and formulas found on them."""

    name: str
    pages: tuple[Page, ...]
    items: pl.DataFrame
    tables: tuple[Table, ...]
    pictures: tuple[Picture, ...]
    formulas: tuple[Formula, ...]

    @property
    def markdown(self) -> str:
        """The whole document as markdown, page after page."""
        return "\n\n".join(page.markdown for page in self.pages)

    @property
    def deep(self) -> tuple[int, ...]:
        """The pages docling read."""
        return tuple(page.number for page in self.pages if page.backend is Backend.DOCLING)
