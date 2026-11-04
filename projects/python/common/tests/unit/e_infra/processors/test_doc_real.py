"""tests/unit/e_infra/processors/doc_real: the reader as the lifespan builds it today — no docling — on real engines.

Companion to `test_doc.py` (fake ports). Here the actual bindings run: anytomd on real text and markup, liteparse
on a real PDF, and the OpenAI-compatible vision model on a real image (skipped without a key). Offline except the
vision case, which needs `MD_VISION_TEST_KEY`."""

import os
import pathlib
import struct
import zlib

import pytest
from pydantic import SecretStr as Secret

from e_infra.processors.doc import DocProcessor
from e_infra.processors.models import Backend
from e_infra.providers.adapters.markdown.anytomd import AnytomdAdapter
from unit.e_infra.conftest import anytomd_args, doc_args
from unit.e_infra.processors.conftest import opened

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
    ("data", "name", "backend", "snippet"),
    [
        (b"Name,Age\nAlice,30\n", "people.csv", Backend.ANYTOMD, "Alice"),
        (b"<h1>Heading</h1><p>Body</p>", "page.html", Backend.ANYTOMD, "Heading"),
        (PDF, "filing.pdf", Backend.LITEPARSE, "10-K"),
    ],
)
async def test_real_engines_read_each_format(data: bytes, name: str, backend: Backend, snippet: str) -> None:
    async with AnytomdAdapter(**anytomd_args()) as anytomd:
        document = await DocProcessor(anytomd, opened(), None, **doc_args()).process(data, name=name)
    assert {page.backend for page in document.pages} == {backend}
    assert snippet in document.markdown


@needs_vision
async def test_real_vision_describes_an_image_inline() -> None:
    assert KEY is not None
    vision = anytomd_args(vision_api_key=Secret(KEY))
    async with AnytomdAdapter(**vision) as anytomd:
        document = await DocProcessor(anytomd, opened(), None, **doc_args()).process(
            png((30, 140, 60)), name="square.png"
        )
    alt = document.markdown.split("![", 1)[1].split("](", 1)[0]
    assert alt.strip()
