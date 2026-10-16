"""tests/unit/e_core/adapters/md/anytomd: the bound engine — connect wiring, PDF vs other formats, warnings, lifecycle, offline.

`PdfConverter`, `convert_bytes_async` and the OpenAI describer are patched, so the contract (a PDF routes to
the converter, any other format to convert_bytes with the describer and limits threaded, warnings flattened,
the not-connected guard) is graded without the real engine or a vision model."""

from types import SimpleNamespace
from typing import Any

import pytest

from e_core.adapters.md.anytomd import AnytomdAdapter
from e_core.adapters.ports import MdConversion
from e_core.core.settings.base import Secret
from e_core.core.settings.md import MDSettings

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
    module = __import__("e_core.adapters.md.anytomd", fromlist=["*"])
    monkeypatch.setattr(module, "PdfConverter", FakeConverter)
    monkeypatch.setattr(module, "AsyncOpenAIDescriber", FakeDescriber)
    monkeypatch.setattr(module, "convert_bytes_async", convert)


def adapter(**conf: Any) -> AnytomdAdapter:
    return AnytomdAdapter(MDSettings(**conf))


async def test_a_pdf_goes_through_the_converter(engine: None) -> None:
    a = adapter(md_pdf_ocr=True, md_pdf_language="spa", md_pdf_workers=4, md_image_describe=False)
    async with a:
        assert await a.convert(b"%PDF", extension="pdf") == MdConversion(markdown="# PDF", warnings=("page 1: bad",))
    assert (PDF_KW["ocr"], PDF_KW["language"], PDF_KW["workers"]) == (True, "spa", 4)


async def test_another_format_goes_through_convert_bytes_with_limits(engine: None) -> None:
    async with adapter(md_strict=True, md_extract_comments=True, md_image_describe=False) as a:
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
    async with adapter(md_vision_api_key=Secret("k")) as a:
        await a.convert(b"png-bytes", extension="png")
    assert (DESC_KW["model"], DESC_KW["api_key"], DESC_KW["prompt"]) == (
        "qwen3.8-flash",
        "k",
        MDSettings().md_vision_prompt,
    )
    assert (convert.calls or (None, None, {}))[2]["async_image_describer"] is not None


async def test_a_pdf_needs_the_lifespan_to_open_the_converter(engine: None) -> None:
    a = adapter()
    with pytest.raises(RuntimeError, match="not connected"):
        await a.convert(b"%PDF", extension="pdf")
    await a.close()
