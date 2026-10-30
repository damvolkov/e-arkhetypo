"""ports/pages: a document's fast pass, page by page — blocks and the signals that tell where a deep reader pays off."""

from typing import Protocol, runtime_checkable

import msgspec

from e_infra.infra.config.processors.doc import DocSignal
from e_infra.ports.provider import Provider


class PageBlock(msgspec.Struct, frozen=True, kw_only=True):
    """One block a fast page reader saw: its kind in the reader's vocabulary, its text (a table's empty), its level when
    a heading, a table's header and rows of cell texts."""

    kind: str
    text: str = ""
    level: int | None = None
    header: tuple[str, ...] = ()
    rows: tuple[tuple[str, ...], ...] = ()


class FastPage(msgspec.Struct, frozen=True, kw_only=True):
    """One page of a fast pass: its number, its Markdown, its blocks in order, and what the reader saw on it that a deep
    reader reads better (`DocSignal`, in their order)."""

    number: int
    markdown: str
    blocks: tuple[PageBlock, ...]
    signals: tuple[DocSignal, ...]


@runtime_checkable
class PagesPort(Provider, Protocol):
    """Every page of a document read at once: what decides which pages a deep reader is asked for."""

    async def parse(self, data: bytes) -> tuple[FastPage, ...]: ...
