"""tests/unit/e_infra/engines/release: releases on the blob store — WORM versions, one current pointer, the writer
that came second refused, a rollback a new version of the same bytes, every file read back against its sha256.

Unit over the memory double (`support.blob.MemoryBlob`, held to GCS's contract); the race on a GCS emulator, where two
writers really interleave (integration)."""

import asyncio
import uuid
from typing import TYPE_CHECKING

import msgspec
import pytest

from e_infra.engines.release import Manifest, ReleaseEngine
from e_infra.infra.errors import ProviderError, ReleaseConflictError, ReleaseCorruptError, ReleaseNotFoundError
from e_infra.providers.drivers.blob.gcs import GCSBlobDriver
from support.blob import MemoryBlob
from unit.e_infra.conftest import gcs_args

if TYPE_CHECKING:
    from e_infra.ports.blob import BlobMeta

CORE = b'<https://example.org/core#B> <http://www.w3.org/2000/01/rdf-schema#label> "B" .\n<https://example.org/core#A> <http://www.w3.org/2000/01/rdf-schema#label> "A" .\n'
APP = b'<https://example.org/app#x> <http://www.w3.org/2000/01/rdf-schema#label> "x" .\n'
QUERIES = b'[{"name": "classes", "sparql": "SELECT ?c WHERE { ?c a ?k }", "params": []}]'
GRAPHS = {"urn:test:core": CORE, "urn:test:app:extra": APP}


def engine(blob: MemoryBlob | GCSBlobDriver) -> ReleaseEngine:
    return ReleaseEngine(blob, prefix="releases/", namespace="urn:test:")


async def first(releases: ReleaseEngine) -> Manifest:
    return await releases.publish(GRAPHS, QUERIES, base=None, proposal="p1", author="root", approver="eva")


async def test_release_none_until_the_first_is_published() -> None:
    async with MemoryBlob() as blob:
        assert await engine(blob).current() is None


async def test_release_publish_writes_a_version_and_points_current_at_it() -> None:
    async with MemoryBlob() as blob:
        releases = engine(blob)
        made = await first(releases)
        assert (made.version, made.parent, await releases.current()) == ("v1", None, made)
        assert (made.graphs["urn:test:core"].triples, made.graphs["urn:test:app:extra"].triples) == (2, 1)
        assert (made.proposal, made.author, made.approver, made.rolled_back_from) == ("p1", "root", "eva", None)


async def test_release_graphs_are_stored_canonical_so_one_content_is_one_sha() -> None:
    async with MemoryBlob() as blob:
        releases = engine(blob)
        made = await first(releases)
        reordered = {
            "urn:test:core": b"".join(reversed(CORE.splitlines(keepends=True))),
            "urn:test:app:extra": APP,
        }
        again = await releases.publish(reordered, QUERIES, base="v1", proposal="p2", author="root", approver="eva")
    assert {name: entry.sha256 for name, entry in again.graphs.items()} == {
        name: entry.sha256 for name, entry in made.graphs.items()
    }


async def test_release_load_reads_back_the_exact_bytes() -> None:
    async with MemoryBlob() as blob:
        releases = engine(blob)
        made = await first(releases)
        loaded = await releases.load(made.version)
    assert (loaded.manifest, loaded.queries, set(loaded.graphs)) == (made, QUERIES, set(GRAPHS))
    assert sorted(loaded.graphs["urn:test:core"].splitlines()) == sorted(CORE.splitlines())


async def test_release_a_proposal_on_a_stale_base_is_refused() -> None:
    async with MemoryBlob() as blob:
        releases = engine(blob)
        await first(releases)
        await releases.publish(GRAPHS, QUERIES, base="v1", proposal="p2", author="root", approver="eva")
        with pytest.raises(ReleaseConflictError, match="v2"):
            await releases.publish(GRAPHS, QUERIES, base="v1", proposal="p3", author="root", approver="eva")
        with pytest.raises(ReleaseConflictError):
            await releases.publish(GRAPHS, QUERIES, base=None, proposal="p4", author="root", approver="eva")


async def test_release_rollback_is_a_new_version_of_the_same_bytes() -> None:
    async with MemoryBlob() as blob:
        releases = engine(blob)
        made = await first(releases)
        await releases.publish(
            {**GRAPHS, "urn:test:app:extra": APP + APP.replace(b'"x"', b'"y"')},
            QUERIES,
            base="v1",
            proposal="p2",
            author="root",
            approver="eva",
        )
        rolled = await releases.rollback("v1", author="root")
        loaded = await releases.load(rolled.version)
    assert (rolled.version, rolled.parent, rolled.rolled_back_from, rolled.graphs) == ("v3", "v2", "v1", made.graphs)
    assert (await releases.current(), loaded.queries) == (rolled, QUERIES)


async def test_release_a_writer_that_lost_leaves_nothing_current_points_at() -> None:
    """The race point is the pointer alone: a version folder is the writer's own, so a loser's folder is an orphan."""
    async with MemoryBlob() as blob:
        releases = engine(blob)
        made = await first(releases)
        folders = {key.split("/")[1] for key in blob.objects if key.count("/") > 1}
        assert folders == {made.graphs["urn:test:core"].file.split("/")[0]}


async def test_release_history_walks_back_from_current() -> None:
    async with MemoryBlob() as blob:
        releases = engine(blob)
        await first(releases)
        await releases.publish(GRAPHS, QUERIES, base="v1", proposal="p2", author="root", approver="eva")
        assert [each.version async for each in releases.history()] == ["v2", "v1"]


async def test_release_a_version_that_does_not_exist_is_not_found() -> None:
    async with MemoryBlob() as blob:
        with pytest.raises(ReleaseNotFoundError):
            await engine(blob).load("v9")
        with pytest.raises(ReleaseNotFoundError):
            await engine(blob).rollback("v9", author="root")


async def test_release_a_file_that_no_longer_matches_its_sha_is_corrupt() -> None:
    async with MemoryBlob() as blob:
        releases = engine(blob)
        made = await first(releases)
        key = f"releases/{made.graphs['urn:test:core'].file}"
        blob.objects[key] = (b"tampered", blob.objects[key][1])
        with pytest.raises(ReleaseCorruptError, match="urn:test:core"):
            await releases.load(made.version)


async def test_release_manifest_round_trips_as_json() -> None:
    async with MemoryBlob() as blob:
        made = await first(engine(blob))
    assert msgspec.json.decode(msgspec.json.encode(made), type=Manifest) == made


class Interleaved(MemoryBlob):
    """The memory double handing the loop over before every call: writers really interleave, as on GCS."""

    async def put(self, key: str, data: bytes, *, if_generation: int | None = None) -> BlobMeta:
        await asyncio.sleep(0)
        return await super().put(key, data, if_generation=if_generation)

    async def head(self, key: str) -> BlobMeta | None:
        await asyncio.sleep(0)
        return await super().head(key)


async def test_release_two_writers_on_one_base_one_wins() -> None:
    async with Interleaved() as blob:
        releases = engine(blob)
        await first(releases)
        outcomes = await asyncio.gather(
            *(
                releases.publish(GRAPHS, QUERIES, base="v1", proposal=f"race-{n}", author="root", approver="eva")
                for n in range(4)
            ),
            return_exceptions=True,
        )
    won = [each for each in outcomes if isinstance(each, Manifest)]
    lost = [each for each in outcomes if isinstance(each, ReleaseConflictError)]
    assert (len(won), len(lost), won[0].version) == (1, 3, "v2")


async def test_release_a_pointer_to_a_missing_folder_is_not_found() -> None:
    async with MemoryBlob() as blob:
        await blob.put("releases/current.json", b'{"version": "v1", "folder": "v1-gone"}')
        with pytest.raises(ReleaseNotFoundError, match="v1-gone"):
            await engine(blob).current()


@pytest.mark.integration
async def test_release_two_writers_on_one_base_one_wins_on_gcs() -> None:
    conf = gcs_args(prefix=f"test/release/{uuid.uuid4().hex}/", api_root="http://127.0.0.1:45013")
    async with GCSBlobDriver(**conf) as blob:
        try:
            await blob.health()
        except ProviderError as error:
            pytest.skip(f"no GCS emulator: {error}")
        releases = engine(blob)
        await first(releases)
        outcomes = await asyncio.gather(
            *(
                releases.publish(GRAPHS, QUERIES, base="v1", proposal=f"race-{n}", author="root", approver="eva")
                for n in range(4)
            ),
            return_exceptions=True,
        )
    won = [each for each in outcomes if isinstance(each, Manifest)]
    lost = [each for each in outcomes if isinstance(each, ReleaseConflictError)]
    assert (len(won), len(lost), won[0].version) == (1, 3, "v2")
