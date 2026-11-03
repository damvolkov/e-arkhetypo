"""e_infra/providers/adapters/extract/rtrafilatura: a page's main content as Markdown, its facts as front matter."""

from typing import TYPE_CHECKING, Final

import pytest
from rtrafilatura.errors import ExtractionError

from e_infra.infra.errors import ParseError
from e_infra.ports.extract import ExtractPort
from e_infra.providers.adapters.extract import rtrafilatura
from e_infra.providers.adapters.extract.rtrafilatura import RtrafilaturaAdapter

if TYPE_CHECKING:
    from unit.e_infra.conftest import Logs

PAGE: Final = (
    b"<html><head><title>On Rivers</title></head><body><nav><a href='/'>Home</a></nav><article><h1>On Rivers</h1>"
    b"<p>" + b"A river is a natural flowing watercourse, usually freshwater, flowing towards the sea. " * 12 + b"</p>"
    b"<p>Rivers carry sediment and shape the valleys they cross over thousands of years.</p></article></body></html>"
)


async def test_rtrafilatura_main_content_without_the_site_around_it() -> None:
    async with RtrafilaturaAdapter() as extractor:
        assert isinstance(extractor, ExtractPort)
        markdown = await extractor.extract(PAGE, url="https://example.org/rivers")
    assert markdown is not None
    assert "natural flowing watercourse" in markdown
    assert "Home" not in markdown


async def test_rtrafilatura_a_page_with_nothing_to_find_answers_none() -> None:
    async with RtrafilaturaAdapter() as extractor:
        assert await extractor.extract(b"<html><body></body></html>") is None


async def test_rtrafilatura_health() -> None:
    async with RtrafilaturaAdapter() as extractor:
        assert await extractor.health()


async def test_rtrafilatura_error_translated(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*_args: object, **_kwargs: object) -> None:
        msg = "tree too large"
        raise ExtractionError(msg)

    monkeypatch.setattr(rtrafilatura.rtrafilatura, "extract", broken)
    async with RtrafilaturaAdapter() as extractor:
        with pytest.raises(ParseError, match="tree too large"):
            await extractor.extract(PAGE)
        assert not await extractor.health()


async def test_rtrafilatura_lifecycle_and_its_failures_are_logged(monkeypatch: pytest.MonkeyPatch, logs: Logs) -> None:
    def broken(*_args: object, **_kwargs: object) -> None:
        msg = "tree too large"
        raise ExtractionError(msg)

    monkeypatch.setattr(rtrafilatura.rtrafilatura, "extract", broken)
    async with RtrafilaturaAdapter() as extractor:
        assert not await extractor.health()
    assert logs.at("info") == ["rtrafilatura opened", "rtrafilatura closed"]
    assert logs.at("error") == ["rtrafilatura failed"]
    assert logs.at("warning") == ["rtrafilatura unhealthy"]
