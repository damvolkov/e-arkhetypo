"""tests/unit/e_infra/processors/md: the MDProcessor — detection of the real engine, per-file errors, ZIP fan-out and bounds, offline.

The engine is a fake `MdConvertPort`; only the *detection* is the real binding, so every route (PDF, office
via zip, a bundle fanned out, an unsupported file) is graded on the formats anytomd actually recognises. A
port that fails marks one file and lets the run continue; the concurrency bound and zip-bomb guard hold."""

import io
import zipfile
from pathlib import Path
from typing import Any, ClassVar, Self

import anyio
import pytest

from e_infra.infra.config.md import MDSettings
from e_infra.infra.errors import InputTooLargeError, UnsupportedFormatError, ZipBombError
from e_infra.ports.markdown import MdConversion
from e_infra.ports.provider import Isolation, Locality, ProviderSpec, Workload
from e_infra.processors.md import MDProcessor
from e_infra.providers.adapters.anytomd import AnytomdAdapter

DETECTOR = AnytomdAdapter(MDSettings())


class FakePort:
    """A `MarkdownPort`: fixed Markdown, optional failure and delay, and a peak-concurrency counter."""

    spec: ClassVar[ProviderSpec] = ProviderSpec("fake", Locality.EMBEDDED, Workload.CPU_BOUND, Isolation.LOOP)

    def __init__(
        self,
        markdown: str = "# md",
        *,
        warnings: tuple[str, ...] = (),
        fail: Exception | None = None,
        delay: float = 0.0,
    ) -> None:
        self.markdown, self.warnings, self.fail, self.delay = markdown, warnings, fail, delay
        self.calls: list[tuple[bytes, str]] = []
        self.flight = self.peak = 0

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Nothing to release."""

    async def health(self) -> bool:
        return True

    def detect(self, name: str, data: bytes) -> str | None:
        """The real engine's detection: every route is graded on the formats anytomd actually recognises."""
        return DETECTOR.detect(name, data)

    async def convert(self, data: bytes, *, extension: str) -> MdConversion:
        self.calls.append((data, extension))
        self.flight += 1
        self.peak = max(self.peak, self.flight)
        try:
            if self.delay:
                await anyio.sleep(self.delay)
            if self.fail:
                raise self.fail
            return MdConversion(markdown=self.markdown, warnings=self.warnings)
        finally:
            self.flight -= 1


def zipped(files: dict[str, bytes]) -> bytes:
    """A deterministic ZIP: a frozen date_time keeps the xdist parametrize ids stable to the byte."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for name, raw in files.items():
            archive.writestr(zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0)), raw)
    return buf.getvalue()


DOCX = zipped({"word/document.xml": b"<w/>"})
PDF = b"%PDF-1.7\n"


def processor(port: FakePort | None = None, **conf: Any) -> MDProcessor:
    return MDProcessor(port or FakePort(), MDSettings(**conf))


##### DETECTION + ROUTING #####
@pytest.mark.parametrize(
    ("data", "name", "source"),
    [
        (PDF, "f.pdf", "pdf"),
        (b"<h1>x</h1>", "p.html", "html"),
        (b"a,b\n1,2\n", "t.csv", "csv"),
        (DOCX, "r.docx", "docx"),
    ],
)
async def test_each_format_reaches_the_engine_named(data: bytes, name: str, source: str) -> None:
    port = FakePort()
    [file] = await processor(port).convert(data, name=name)
    assert (file.source, file.markdown, file.name) == (source, "# md", Path(name).stem + ".md")
    assert port.calls == [(data, source)]


async def test_an_unsupported_file_is_refused_before_the_engine() -> None:
    port = FakePort()
    with pytest.raises(UnsupportedFormatError, match="not a format"):
        await processor(port).convert(b"\xff\xfe\x00\x01blob", name="mystery")
    assert port.calls == []


async def test_an_oversized_file_is_refused() -> None:
    with pytest.raises(InputTooLargeError, match="over MD_MAX_INPUT_BYTES"):
        await processor(md_max_input_bytes=4).convert(b"123456789", name="big.txt")


async def test_a_failing_engine_marks_the_file_not_the_run() -> None:
    [file] = await processor(FakePort(fail=RuntimeError("engine down"))).convert(b"a,b\n", name="t.csv")
    assert (file.markdown, file.error) == ("", "RuntimeError: engine down")


async def test_bytes_without_a_name_default_to_document() -> None:
    [file] = await processor().convert(PDF)
    assert file.name == "document.md"


async def test_a_path_is_read_and_named(tmp_path: Path) -> None:
    source = tmp_path / "report.html"
    source.write_bytes(b"<h1>Hi</h1>")
    [file] = await processor().convert(source)
    assert (file.name, file.source) == ("report.md", "html")


##### ZIP FAN-OUT #####
async def test_a_zip_renders_each_member_with_its_path() -> None:
    port = FakePort()
    files = await processor(port).convert(zipped({"notes.txt": b"hi", "src/app.py": b"print(1)"}), name="bundle.zip")
    assert [(f.name, f.path, f.source) for f in files] == [
        ("notes.md", "notes.txt", "txt"),
        ("app.md", "src/app.py", "code"),
    ]
    assert len(port.calls) == 2


async def test_a_nested_zip_uploads_member_paths() -> None:
    inner = zipped({"deep.txt": b"x"})
    [file] = await processor().convert(zipped({"inner.zip": inner}), name="outer.zip")
    assert (file.path, file.name) == ("inner.zip/deep.txt", "deep.md")


async def test_members_are_bounded_by_concurrency() -> None:
    port = FakePort(delay=0.02)
    bundle = zipped({f"m{i}.txt": b"x" for i in range(5)})
    await processor(port, md_concurrency=2).convert(bundle, name="z.zip")
    assert len(port.calls) == 5
    assert port.peak <= 2


async def test_a_zip_with_too_many_entries_is_refused() -> None:
    with pytest.raises(ZipBombError, match="over limit"):
        await processor(md_zip_max_entries=1).convert(zipped({"a.txt": b"x", "b.txt": b"y"}), name="z.zip")


async def test_a_zip_that_unpacks_too_big_is_refused() -> None:
    with pytest.raises(ZipBombError, match="over limit"):
        await processor(md_zip_max_bytes=100).convert(zipped({"a.txt": b"x" * 1000}), name="z.zip")
