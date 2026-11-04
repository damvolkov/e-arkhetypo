"""processors/models: what the processors hand out — a document read, typed.

Interior data built by code: frozen, slotted dataclasses, never a boundary model. Whoever read a page
(liteparse or docling, see `Page.backend`), its objects look the same: every one keeps its `ref` — the
engine and its own pointer (`docling:110-119#/tables/3`, `liteparse:p44/b7`) — and the `page` it sits
on, so anything extracted from it traces back to where it was read. Labels follow docling's vocabulary
(`section_header`, `text`, `list_item`, `formula`, ...): liteparse blocks are mapped onto it."""

from dataclasses import dataclass
from enum import StrEnum, auto
from typing import TYPE_CHECKING, Final

import polars as pl

if TYPE_CHECKING:
    from e_infra.infra.config.processors import DocSignal

HEADINGS: Final[frozenset[str]] = frozenset({"title", "section_header"})
BODY: Final[frozenset[str]] = frozenset({"text", "list_item", "paragraph"})


class Backend(StrEnum):
    """The engine that read a page: liteparse and docling a PDF's, anytomd any other document's, whole."""

    LITEPARSE = auto()
    DOCLING = auto()
    ANYTOMD = auto()


class Element(StrEnum):
    """What a reading is asked for: each decides which pages docling reads and what it runs on them."""

    TEXT = auto()
    TABLES = auto()
    PICTURES = auto()
    FORMULAS = auto()


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
    label, text, level, backend), the tables, pictures and formulas found on them, and the reader's notes on what it
    could not read (`warnings`, anytomd's)."""

    name: str
    pages: tuple[Page, ...]
    items: pl.DataFrame
    tables: tuple[Table, ...]
    pictures: tuple[Picture, ...]
    formulas: tuple[Formula, ...]
    warnings: tuple[str, ...] = ()

    @property
    def markdown(self) -> str:
        """The whole document as markdown, page after page."""
        return "\n\n".join(page.markdown for page in self.pages)

    @property
    def deep(self) -> tuple[int, ...]:
        """The pages docling read."""
        return tuple(page.number for page in self.pages if page.backend is Backend.DOCLING)

    @property
    def sections(self) -> list[Section]:
        """Every heading with the body text under it, up to the next heading — one pass over the items frame.

        Text before the first heading belongs to no section and is left out."""
        frame = (
            self.items.with_columns(section=pl.col("label").is_in(HEADINGS).cum_sum())
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
