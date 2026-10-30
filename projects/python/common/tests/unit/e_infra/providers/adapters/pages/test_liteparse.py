"""e_infra/providers/adapters/pages/liteparse: the fast pass on the real filing — blocks, tables and the signals."""

from pathlib import Path
from typing import TYPE_CHECKING, Final

import pytest

from e_infra.infra.config.processors.doc import DocSignal
from e_infra.infra.config.providers.adapters.pages.liteparse import LiteparseSettings
from e_infra.infra.errors import ParseError
from e_infra.ports.pages import FastPage, PagesPort
from e_infra.providers.adapters.pages.liteparse import LiteparseAdapter

if TYPE_CHECKING:
    from unit.e_infra.conftest import Logs

FILING: Final[Path] = Path(__file__).resolve().parents[5] / "resources" / "documents" / "filing.pdf"
TEXT, WORKFORCE, STATEMENT, SCAN = 1, 2, 3, 4


async def test_liteparse_signals_tell_text_tables_and_scans_apart() -> None:
    async with LiteparseAdapter(LiteparseSettings()) as pages:
        assert isinstance(pages, PagesPort)
        read = {page.number: page for page in await pages.parse(FILING.read_bytes())}
    assert all(isinstance(page, FastPage) for page in read.values())
    assert read[TEXT].signals == read[WORKFORCE].signals == ()
    assert DocSignal.TABLE in read[STATEMENT].signals
    assert {DocSignal.SCANNED, DocSignal.IMAGES} <= set(read[SCAN].signals)


async def test_liteparse_blocks_carry_tables_and_headings() -> None:
    async with LiteparseAdapter(LiteparseSettings()) as pages:
        read = {page.number: page for page in await pages.parse(FILING.read_bytes())}
    tables = [block for block in read[STATEMENT].blocks if block.kind == "table"]
    assert tables
    assert all(block.rows for block in tables)
    assert any(block.kind == "heading" and block.level is not None for block in read[TEXT].blocks)
    assert all(page.markdown for page in read.values())


async def test_liteparse_unopen_and_closed() -> None:
    pages = LiteparseAdapter(LiteparseSettings())
    assert not await pages.health()
    with pytest.raises(ParseError, match="not open"):
        await pages.parse(b"%PDF")
    async with pages:
        assert await pages.health()
    assert not await pages.health()


async def test_liteparse_error_translated() -> None:
    """liteparse's own error never leaves the adapter."""
    async with LiteparseAdapter(LiteparseSettings()) as pages:
        with pytest.raises(ParseError):
            await pages.parse(b"not a pdf at all")


async def test_liteparse_lifecycle_and_its_failures_are_logged(logs: Logs) -> None:
    pages = LiteparseAdapter(LiteparseSettings())
    assert not await pages.health()
    async with pages:
        with pytest.raises(ParseError):
            await pages.parse(b"not a pdf at all")
    assert logs.at("info") == ["liteparse opened", "liteparse closed"]
    assert logs.at("error") == ["liteparse failed"]
    assert logs.at("warning") == ["liteparse unhealthy"]
    assert logs.at("debug") == ["liteparse parse"]
