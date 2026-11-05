"""engines/release: a set of RDF graphs released on a blob store — WORM versions, one pointer, one writer at a time.

A release is a folder of its own (`{version}-{token}/`) holding a canonical N-Triples file per named graph, the typed
queries, and the manifest (version, parent, proposal, author, approver, every file's sha256 and triple count). The
current release is the pointer `current.json`: publishing writes the folder, then moves the pointer with a conditional
write on the generation it read — the one race point. Two writers on one base: one moves it, the other gets
`ReleaseConflictError`; its folder is an orphan nothing points at, harmless on a store that is never rewritten. A
proposal made on another base than the current release is refused before any write. A rollback is a new version whose
manifest points at the old files — the same bytes, never copied. Every file read back is checked against its sha256.
The engine keeps a reference to the store and its settings, nothing else."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

import msgspec

from e_infra.infra.errors import (
    BlobNotFoundError,
    BlobPreconditionError,
    ReleaseConflictError,
    ReleaseCorruptError,
    ReleaseNotFoundError,
)
from e_infra.infra.logger import logger
from e_infra.ops.hash import hash_bytes

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping

    from e_infra.ports.blob import BlobMeta, BlobPort

CURRENT: Final[str] = "current.json"
MANIFEST: Final[str] = "manifest.json"
QUERIES: Final[str] = "queries.json"


##### VALUES #####
class GraphEntry(msgspec.Struct, frozen=True, kw_only=True):
    """One graph's file (its key under the release prefix), its triple count, its sha256."""

    file: str
    triples: int
    sha256: str


class Manifest(msgspec.Struct, frozen=True, kw_only=True):
    """What a release is: its place in the chain, who made it, and every file it holds, by graph."""

    version: str
    folder: str
    parent: str | None
    parent_folder: str | None
    proposal: str | None
    author: str
    approver: str | None
    created: datetime
    graphs: dict[str, GraphEntry]
    queries: GraphEntry
    rolled_back_from: str | None = None


class Pointer(msgspec.Struct, frozen=True, kw_only=True):
    version: str
    folder: str


class Release(msgspec.Struct, frozen=True, kw_only=True):
    """A release read back whole: its manifest, its graphs as canonical N-Triples, its queries."""

    manifest: Manifest
    graphs: dict[str, bytes]
    queries: bytes


##### ENGINE #####
class ReleaseEngine:
    """Publishes, reads, rolls back and walks a graph set's releases on a `BlobPort`. `namespace` is the IRI prefix
    the graph names share: a file is named by the rest."""

    __slots__ = ("_blob", "_namespace", "_prefix")

    def __init__(self, blob: BlobPort, *, prefix: str, namespace: str) -> None:
        self._prefix = prefix
        self._namespace = namespace
        self._blob = blob

    ##### PRIVATE #####

    def _common_key(self, name: str) -> str:
        return f"{self._prefix}{name}"

    @staticmethod
    def _common_canonical(data: bytes) -> bytes:
        """N-Triples one statement a line, sorted, without duplicates: one content, one sha256."""
        lines = sorted({line.strip() for line in data.splitlines() if line.strip() and not line.startswith(b"#")})
        return b"".join(line + b"\n" for line in lines)

    def _common_file(self, graph: str) -> str:
        return graph.removeprefix(self._namespace).replace(":", "-") + ".nt"

    async def _common_pointer(self) -> tuple[BlobMeta | None, Pointer | None]:
        """The pointer's generation and the release it names; both None before the first."""
        meta = await self._blob.head(self._common_key(CURRENT))
        match meta:
            case None:
                return None, None
            case _:
                return meta, msgspec.json.decode(await self._blob.get(self._common_key(CURRENT)), type=Pointer)

    async def _common_manifest(self, folder: str) -> Manifest:
        try:
            return msgspec.json.decode(await self._blob.get(self._common_key(f"{folder}/{MANIFEST}")), type=Manifest)
        except BlobNotFoundError as error:
            raise ReleaseNotFoundError(folder) from error

    async def _common_find(self, version: str) -> Manifest:
        """The manifest of `version` on the current chain."""
        found = [each async for each in self.history() if each.version == version]
        match found:
            case [manifest, *_]:
                return manifest
            case _:
                msg = f"no release {version} on the current chain"
                raise ReleaseNotFoundError(msg)

    async def _common_point(self, manifest: Manifest, meta: BlobMeta | None) -> Manifest:
        """Write the manifest into its folder, then move the pointer while it still holds the generation read."""
        await self._blob.put(
            self._common_key(f"{manifest.folder}/{MANIFEST}"), msgspec.json.encode(manifest), if_generation=0
        )
        pointer = msgspec.json.encode(Pointer(version=manifest.version, folder=manifest.folder))
        try:
            await self._blob.put(
                self._common_key(CURRENT), pointer, if_generation=0 if meta is None else meta.generation
            )
        except BlobPreconditionError as error:
            logger.warning("release lost the race", version=manifest.version, folder=manifest.folder)
            msg = f"another writer published {manifest.version} first"
            raise ReleaseConflictError(msg) from error
        logger.info("release published", version=manifest.version, parent=manifest.parent, proposal=manifest.proposal)
        return manifest

    async def _load_file(self, entry: GraphEntry, label: str) -> bytes:
        data = await self._blob.get(self._common_key(entry.file))
        match hash_bytes(data) == entry.sha256:
            case True:
                return data
            case _:
                msg = f"{label}: {entry.file} no longer matches its sha256"
                raise ReleaseCorruptError(msg)

    ############################################################

    ##### PUBLIC #####

    async def current(self) -> Manifest | None:
        """The current release's manifest; None before the first."""
        _, pointer = await self._common_pointer()
        return None if pointer is None else await self._common_manifest(pointer.folder)

    async def publish(
        self,
        graphs: Mapping[str, bytes],
        queries: bytes,
        *,
        base: str | None,
        proposal: str,
        author: str,
        approver: str,
    ) -> Manifest:
        """A new release of `graphs` (named graph → N-Triples) and `queries`, on `base`, the release the proposal was
        made against — refused when the current release is another, or when another writer moves it first."""
        meta, pointer = await self._common_pointer()
        held = None if pointer is None else pointer.version
        match held == base:
            case False:
                msg = f"the release is {held}; the proposal was made on {base}"
                raise ReleaseConflictError(msg)
        version = f"v{int(held[1:]) + 1}" if held else "v1"
        folder = f"{version}-{uuid.uuid4().hex[:12]}"
        canonical = {graph: self._common_canonical(data) for graph, data in graphs.items()}
        entries = {
            graph: GraphEntry(
                file=f"{folder}/{self._common_file(graph)}", triples=data.count(b"\n"), sha256=hash_bytes(data)
            )
            for graph, data in canonical.items()
        }
        _ = [
            await self._blob.put(self._common_key(entries[graph].file), data, if_generation=0)
            for graph, data in canonical.items()
        ]
        await self._blob.put(self._common_key(f"{folder}/{QUERIES}"), queries, if_generation=0)
        manifest = Manifest(
            version=version,
            folder=folder,
            parent=held,
            parent_folder=None if pointer is None else pointer.folder,
            proposal=proposal,
            author=author,
            approver=approver,
            created=datetime.now(UTC),
            graphs=entries,
            queries=GraphEntry(file=f"{folder}/{QUERIES}", triples=0, sha256=hash_bytes(queries)),
        )
        return await self._common_point(manifest, meta)

    async def load(self, version: str) -> Release:
        """A release of the current chain, every file checked against its sha256."""
        manifest = await self._common_find(version)
        graphs = {graph: await self._load_file(entry, graph) for graph, entry in manifest.graphs.items()}
        return Release(manifest=manifest, graphs=graphs, queries=await self._load_file(manifest.queries, "queries"))

    async def rollback(self, version: str, *, author: str) -> Manifest:
        """A new release holding the bytes of `version`: the chain moves forward, its past stays as it was."""
        meta, pointer = await self._common_pointer()
        target = await self._common_find(version)
        held = None if pointer is None else pointer.version
        new = f"v{int(held[1:]) + 1}" if held else "v1"
        manifest = msgspec.structs.replace(
            target,
            version=new,
            folder=f"{new}-{uuid.uuid4().hex[:12]}",
            parent=held,
            parent_folder=None if pointer is None else pointer.folder,
            proposal=None,
            author=author,
            approver=None,
            created=datetime.now(UTC),
            rolled_back_from=version,
        )
        return await self._common_point(manifest, meta)

    async def history(self) -> AsyncIterator[Manifest]:
        """Every release from the current back to the first, by their parents."""
        _, pointer = await self._common_pointer()
        folder = None if pointer is None else pointer.folder
        ### a real loop: the chain is followed one parent at a time, each read from the store.
        while folder is not None:
            manifest = await self._common_manifest(folder)
            yield manifest
            folder = manifest.parent_folder
