"""e_infra/providers/adapters/markdown/anytomd: the bound engine — connect wiring, PDF vs other formats, warnings, lifecycle, offline.

`PdfConverter`, `convert_bytes_async` and the OpenAI describer are patched, so the contract (a PDF routes to
the converter, any other format to convert_bytes with the describer and limits threaded, warnings flattened,
the not-connected guard) is graded without the real engine or a vision model."""

import io
import zipfile
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from e_infra.infra.config.base import Secret
from e_infra.infra.config.providers.adapters.markdown.anytomd import AnytomdSettings
from e_infra.infra.errors import ParseError
from e_infra.ports.markdown import MarkdownPort, MdConversion
from e_infra.providers.adapters.markdown import anytomd
from e_infra.providers.adapters.markdown.anytomd import AnytomdAdapter

if TYPE_CHECKING:
    from unit.e_infra.conftest import Logs

PDF_KW: dict[str, Any] = {}
DESC_KW: dict[str, Any] = {}


class FakeConverter:
    def __init__(self, **kwargs: Any) -> None:
        PDF_KW.clear()
        PDF_KW.update(kwargs)

    async def convert_bytes_async(self, data: bytes) -> SimpleNamespace:
        return SimpleNamespace(markdown="# PDF", pages=2, warnings=("page 1: bad",))


class FakeDescriber:
    def __init__(self, **kwargs: Any) -> None:
        DESC_KW.clear()
        DESC_KW.update(kwargs)


class Result:
    markdown = "# A"
    warnings = (SimpleNamespace(message="skipped a chart"),)


class ConvertBytes:
    def __init__(self) -> None:
        self.calls: tuple[bytes, str, dict[str, Any]] | None = None

    async def __call__(self, data: bytes, extension: str, **kwargs: Any) -> Result:
        self.calls = (data, extension, kwargs)
        return Result()


convert = ConvertBytes()


@pytest.fixture
def engine(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(anytomd, "PdfConverter", FakeConverter)
    monkeypatch.setattr(anytomd, "AsyncOpenAIDescriber", FakeDescriber)
    monkeypatch.setattr(anytomd, "convert_bytes_async", convert)


def adapter(**conf: Any) -> AnytomdAdapter:
    return AnytomdAdapter(AnytomdSettings(**conf))


async def test_a_pdf_goes_through_the_converter(engine: None) -> None:
    a = adapter(pdf_ocr=True, pdf_language="spa", pdf_workers=4, image_describe=False)
    async with a:
        assert await a.convert(b"%PDF", extension="pdf") == MdConversion(markdown="# PDF", warnings=("page 1: bad",))
    assert (PDF_KW["ocr"], PDF_KW["language"], PDF_KW["workers"]) == (True, "spa", 4)


async def test_another_format_goes_through_convert_bytes_with_limits(engine: None) -> None:
    async with adapter(strict=True, extract_comments=True, image_describe=False) as a:
        out = await a.convert(b"<h1>Hi</h1>", extension="html")
    data, extension, kwargs = convert.calls or (b"", "", {})
    assert (out.markdown, out.warnings) == ("# A", ("skipped a chart",))
    assert (data, extension, kwargs["async_image_describer"], kwargs["strict"], kwargs["extract_comments"]) == (
        b"<h1>Hi</h1>",
        "html",
        None,
        True,
        True,
    )


async def test_the_vision_describer_is_wired_from_settings(engine: None) -> None:
    async with adapter(vision_api_key=Secret("k")) as a:
        await a.convert(b"png-bytes", extension="png")
    assert (DESC_KW["model"], DESC_KW["api_key"], DESC_KW["prompt"]) == (
        "qwen3.8-flash",
        "k",
        AnytomdSettings().vision_prompt,
    )
    assert (convert.calls or (None, None, {}))[2]["async_image_describer"] is not None


async def test_without_a_vision_key_images_stay_undescribed(engine: None) -> None:
    async with adapter(image_describe=True, vision_api_key=None) as a:
        await a.convert(b"<p>x</p>", extension="html")
    assert (convert.calls or (None, None, {"async_image_describer": "unset"}))[2]["async_image_describer"] is None


async def test_a_pdf_needs_the_lifespan_to_open_the_converter(engine: None) -> None:
    a = adapter()
    with pytest.raises(ParseError, match="not open"):
        await a.convert(b"%PDF", extension="pdf")
    await a.__aexit__(None, None, None)


async def test_health(engine: None) -> None:
    """The engine renders a line of text and the PDF converter is open; closed, nothing answers."""
    a = adapter(image_describe=False)
    async with a:
        assert isinstance(a, MarkdownPort)
        assert await a.health()
    assert convert.calls is not None
    assert convert.calls[:2] == (b"ping", "txt")
    assert not await a.health()


async def test_the_engines_failure_is_a_parse_error(engine: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """anytomd's own error never leaves the adapter."""

    async def broken(*_args: Any, **_kwargs: Any) -> None:
        msg = "malformed"
        raise anytomd.ConvertError(msg)

    monkeypatch.setattr(anytomd, "convert_bytes_async", broken)
    async with adapter(image_describe=False) as a:
        with pytest.raises(ParseError, match="malformed"):
            await a.convert(b"x", extension="html")


@pytest.mark.parametrize(
    ("name", "data", "expected"),
    [("a.txt", b"hello", "txt"), ("a.unknownext", b"\x00\x01\x02", None)],
    ids=["text", "unknown"],
)
async def test_detect_names_the_format(name: str, data: bytes, expected: str | None) -> None:
    """The real engine's detection, no lifecycle needed: a format, or None outside the spectrum."""
    assert AnytomdAdapter(AnytomdSettings()).detect(name, data) == expected


@pytest.mark.parametrize(
    ("entries", "expected"),
    [({"word/document.xml": b"<w/>"}, "docx"), ({"notes.txt": b"hi"}, "zip")],
    ids=["office-archive", "plain-bundle"],
)
async def test_detect_names_an_archive_as_what_it_is(entries: dict[str, bytes], expected: str) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        _ = [archive.writestr(name, raw) for name, raw in entries.items()]
    assert AnytomdAdapter(AnytomdSettings()).detect("bundle.zip", buf.getvalue()) == expected


async def test_the_engines_failure_and_the_lifecycle_are_logged(
    engine: None, monkeypatch: pytest.MonkeyPatch, logs: Logs
) -> None:
    async def broken(*_args: Any, **_kwargs: Any) -> None:
        msg = "malformed"
        raise anytomd.ConvertError(msg)

    monkeypatch.setattr(anytomd, "convert_bytes_async", broken)
    a = adapter(image_describe=False)
    async with a:
        with pytest.raises(ParseError):
            await a.convert(b"x", extension="html")
        assert not await a.health()
    assert logs.at("info") == ["anytomd opened", "anytomd closed"]
    assert logs.at("error") == ["anytomd failed"] * 2
    assert logs.at("warning") == ["anytomd unhealthy"]
    assert logs.at("debug") == ["anytomd convert"] * 2
