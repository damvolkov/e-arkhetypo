"""scripts/conversions: record the test corpus through the live docling-serve — span by span, as the processor asks.

Every document listed in `tests/resources/documents/corpus.yaml` is checked against its sha256, then read
by the `DocProcessor` with default settings over the same providers the app uses (`DoclingSettings` from the
environment, pictures at scale 1). Each span the processor routes to docling is recorded as the server
answered it — its own `page_range`, its own markdown — and the recording is written as
`tests/resources/conversions/<stem>.json.gz`: `{"first-last": DocumentConversion}`, msgspec-encoded,
gzipped. Tests replay these instead of a server (`support.docling.GoldenPort`): offline, and minutes per
document cheaper. Re-run (`make conversions`) whenever docling-serve or the routing changes: the diff
shows what moved. Documents are read two at a time, bounded: the server's own queue does the rest."""

import asyncio
import gzip
import hashlib
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Final, Self

import eserde
import msgspec

from infra.config.providers.drivers.documents.docling import DoclingSettings
from processors.doc import DocProcessor
from providers.adapters.pages.liteparse import LiteparseAdapter
from providers.drivers.documents.docling import DoclingDriver
from providers.drivers.http.wreq import WreqDriver

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ports.documents import DocumentConversion
    from ports.pages import PagesPort
    from ports.provider import ProviderSpec

ROOT: Final[Path] = Path(__file__).resolve().parents[1] / "tests" / "resources"
DOCUMENTS: Final[Path] = ROOT / "documents"
CONVERSIONS: Final[Path] = ROOT / "conversions"
PARALLEL: Final[int] = 2


class RecordingPort:
    """The live driver behind `DocumentPort`, every span's answer kept by its page range; its lifecycle is `main`'s."""

    spec: ClassVar[ProviderSpec] = DoclingDriver.spec

    def __init__(self, driver: DoclingDriver) -> None:
        self.driver = driver
        self.spans: dict[str, DocumentConversion] = {}

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        """The driver closes with `main`'s stack, never here."""

    async def health(self) -> bool:
        return await self.driver.health()

    async def convert(
        self, source: Any, *, filename: str = "", options: Mapping[str, object] | None = None
    ) -> DocumentConversion:
        conversion = await self.driver.convert(source, filename=filename, options=options)
        first, last = dict(options or {})["page_range"]  # ty: ignore[not-iterable]
        self.spans[f"{first}-{last}"] = conversion
        return conversion


async def record(driver: DoclingDriver, pages: PagesPort, entry: dict[str, str], gate: asyncio.Semaphore) -> str:
    """One corpus entry: verified, read, its spans written; its line of the report returned."""
    file = DOCUMENTS / entry["file"]
    match hashlib.sha256(file.read_bytes()).hexdigest() == entry["sha256"]:
        case False:
            msg = f"{file} does not match its sha256 in corpus.yaml"
            raise ValueError(msg)
        case True:
            port = RecordingPort(driver)
            async with gate:
                await DocProcessor(port, pages).process(file)
    target = CONVERSIONS / f"{file.stem}.json.gz"
    target.write_bytes(gzip.compress(msgspec.json.encode(dict(sorted(port.spans.items()))), mtime=0))
    seconds = sum(conversion.seconds for conversion in port.spans.values())
    return f"{file.name}: {len(port.spans)} spans, {seconds:.0f}s, {target.stat().st_size // 1024} KB"


async def main() -> None:
    corpus = eserde.load(DOCUMENTS / "corpus.yaml")
    CONVERSIONS.mkdir(exist_ok=True)
    gate = asyncio.Semaphore(PARALLEL)
    async with (
        WreqDriver() as http,
        DoclingDriver(http, DoclingSettings(docling_images_scale=1.0)) as driver,
        LiteparseAdapter() as pages,
        asyncio.TaskGroup() as group,
    ):
        tasks = [group.create_task(record(driver, pages, entry, gate)) for entry in corpus["documents"]]
    print("\n".join(task.result() for task in tasks))


if __name__ == "__main__":
    asyncio.run(main())
