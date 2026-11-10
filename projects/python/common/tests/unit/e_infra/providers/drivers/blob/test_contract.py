"""tests/unit/e_infra/providers/drivers/blob/contract: `BlobPort` as a contract — GCS on an emulator, the GCS driver
on a stand-in of GCS's JSON API (`support.gcs`, no service), and the memory double answer every case alike.

Each run writes under a prefix of its own, so a bucket shared by every run never mixes them."""

import re
import uuid
from typing import TYPE_CHECKING

import pytest

from e_infra.infra.errors import BlobNotFoundError, BlobPreconditionError
from e_infra.ports.blob import BlobMeta, BlobPort
from e_infra.providers.drivers.blob.gcs import GCSBlobDriver
from support.blob import MemoryBlob
from support.gcs import FakeGCS
from unit.e_infra.conftest import gcs_args

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from pytest_httpserver import HTTPServer

EMULATOR = "http://127.0.0.1:45013"


@pytest.fixture(params=[pytest.param("gcs", marks=pytest.mark.integration), "stand-in", "memory"])
async def blob(request: pytest.FixtureRequest, httpserver: HTTPServer) -> AsyncIterator[BlobPort]:
    match request.param:
        case "stand-in":
            httpserver.expect_request(re.compile(".*")).respond_with_handler(FakeGCS().serve)
            driver: BlobPort = GCSBlobDriver(
                **gcs_args(prefix="test/", api_root=httpserver.url_for("").rstrip("/"), page=2)
            )
        case "gcs":
            conf = gcs_args(prefix=f"test/contract/{uuid.uuid4().hex}/", api_root=EMULATOR, page=2)
            driver = GCSBlobDriver(**conf)
        case _:
            driver = MemoryBlob()
    async with driver:
        await driver.health()
        yield driver


async def test_blob_meets_the_port(blob: BlobPort) -> None:
    assert isinstance(blob, BlobPort)


async def test_blob_put_then_get_and_head(blob: BlobPort) -> None:
    put = await blob.put("raw/a", b"one")
    assert (await blob.get("raw/a"), await blob.head("raw/a")) == (b"one", put)
    assert (put.key, put.size, put.generation > 0) == ("raw/a", 3, True)


async def test_blob_create_only_refuses_a_second_writer(blob: BlobPort) -> None:
    await blob.put("raw/b", b"one", if_generation=0)
    with pytest.raises(BlobPreconditionError):
        await blob.put("raw/b", b"two", if_generation=0)
    assert await blob.get("raw/b") == b"one"


async def test_blob_update_holds_only_on_the_generation_read(blob: BlobPort) -> None:
    first = await blob.put("current", b"v1")
    second = await blob.put("current", b"v2", if_generation=first.generation)
    with pytest.raises(BlobPreconditionError):
        await blob.put("current", b"v3", if_generation=first.generation)
    assert (await blob.get("current"), second.generation > first.generation) == (b"v2", True)


async def test_blob_missing_is_none_to_head_and_an_error_to_get(blob: BlobPort) -> None:
    assert await blob.head("nowhere") is None
    with pytest.raises(BlobNotFoundError):
        await blob.get("nowhere")


async def test_blob_list_walks_a_prefix_lazily_across_pages(blob: BlobPort) -> None:
    _ = [await blob.put(f"releases/v1/{name}", name.encode()) for name in ("core", "app", "instance")]
    await blob.put("raw/x", b"x")
    found = [meta async for meta in blob.list("releases/v1/")]
    assert sorted(meta.key for meta in found) == ["releases/v1/app", "releases/v1/core", "releases/v1/instance"]
    assert all(isinstance(meta, BlobMeta) for meta in found)
