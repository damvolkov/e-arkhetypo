"""tests/unit/e_infra/processors/md_real: the whole chain against the real engine — every format converted end to end.

Companion to `test_md.py` (fake port). Here the actual binding runs: anytomd on real text/markup, the bundled
liteparse on a real PDF, and the OpenAI-compatible vision model on a real image (skipped without a key). Offline
except the vision case, which needs `MD_VISION_TEST_KEY`."""

import os
import pathlib
import struct
import zlib

import pytest

from e_infra.adapters.anytomd import AnytomdAdapter
from e_infra.infra.settings.base import Secret
from e_infra.infra.settings.md import MDSettings
from e_infra.processors.md import MDProcessor

RESOURCES = pathlib.Path(__file__).resolve().parents[3] / "resources"
PDF = (RESOURCES / "documents" / "filing.pdf").read_bytes()
KEY = os.environ.get("MD_VISION_TEST_KEY")
needs_vision = pytest.mark.skipif(not KEY, reason="no vision key (set MD_VISION_TEST_KEY)")


def png(rgb: tuple[int, int, int]) -> bytes:
    raw = b"".join(b"\x00" + bytes(rgb) * 40 for _ in range(40))

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 40, 40, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


@pytest.mark.parametrize(
    ("data", "name", "source", "snippet"),
    [
        (b"Name,Age\nAlice,30\n", "people.csv", "csv", "Alice"),
        (b"<h1>Heading</h1><p>Body</p>", "page.html", "html", "Heading"),
        (PDF, "filing.pdf", "pdf", "10-K"),
    ],
)
async def test_real_engine_renders_each_format(data: bytes, name: str, source: str, snippet: str) -> None:
    async with AnytomdAdapter(MDSettings()) as anytomd:
        [file] = await MDProcessor(anytomd, MDSettings()).convert(data, name=name)
    assert (file.source, file.error) == (source, "")
    assert snippet in file.markdown


@needs_vision
async def test_real_vision_describes_an_image_inline() -> None:
    assert KEY is not None
    settings = MDSettings(md_vision_api_key=Secret(KEY))
    async with AnytomdAdapter(settings) as anytomd:
        [file] = await MDProcessor(anytomd, settings).convert(png((30, 140, 60)), name="square.png")
    assert file.source == "image"
    alt = file.markdown.split("![", 1)[1].split("](", 1)[0]
    assert alt.strip()
