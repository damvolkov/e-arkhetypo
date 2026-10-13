"""scripts/conversions: convert the test corpus through the live docling-serve into golden conversions.

Every document listed in `tests/resources/documents/corpus.yaml` is checked against its sha256, then
converted by the same adapter the app uses (`DoclingSettings` from the environment, pictures at scale
1) and written as `tests/resources/conversions/<stem>.json.gz`: the `DocumentConversion` msgspec-encoded,
gzipped. Tests read these instead of a server — offline, and a hundred seconds per document cheaper.
Re-run (`make conversions`) whenever docling-serve is upgraded: the diff shows what the new models changed.
Conversions run two at a time, bounded: the server's own queue does the rest."""

import asyncio
import gzip
import hashlib
from pathlib import Path
from typing import Final

import eserde
import msgspec

from adapters.docling import DoclingAdapter
from core.settings.docling import DoclingSettings

ROOT: Final[Path] = Path(__file__).resolve().parents[1] / "tests" / "resources"
DOCUMENTS: Final[Path] = ROOT / "documents"
CONVERSIONS: Final[Path] = ROOT / "conversions"
PARALLEL: Final[int] = 2


async def convert(adapter: DoclingAdapter, entry: dict[str, str], gate: asyncio.Semaphore) -> str:
    """One corpus entry: verified, converted, written; its line of the report returned."""
    file = DOCUMENTS / entry["file"]
    match hashlib.sha256(file.read_bytes()).hexdigest() == entry["sha256"]:
        case False:
            msg = f"{file} does not match its sha256 in corpus.yaml"
            raise ValueError(msg)
        case True:
            async with gate:
                conversion = await adapter.convert(file)
    target = CONVERSIONS / f"{file.stem}.json.gz"
    target.write_bytes(gzip.compress(msgspec.json.encode(conversion), mtime=0))
    return f"{file.name}: {conversion.status}, {conversion.seconds:.0f}s, {target.stat().st_size // 1024} KB"


async def main() -> None:
    corpus = eserde.load(DOCUMENTS / "corpus.yaml")
    CONVERSIONS.mkdir(exist_ok=True)
    gate = asyncio.Semaphore(PARALLEL)
    async with DoclingAdapter(DoclingSettings(docling_images_scale=1.0)) as adapter, asyncio.TaskGroup() as group:
        tasks = [group.create_task(convert(adapter, entry, gate)) for entry in corpus["documents"]]
    print("\n".join(task.result() for task in tasks))


if __name__ == "__main__":
    asyncio.run(main())
