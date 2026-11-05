"""tests/unit/e_infra/providers/drivers/blob/gcs: a bucket that refuses, does not answer, or a driver not open is the
port's `BlobError` on every call — never aiohttp's own error past the border."""

import re
from typing import TYPE_CHECKING, Any

import pytest

from e_infra.infra.errors import BlobError
from e_infra.providers.drivers.blob.gcs import GCSBlobDriver
from support.gcs import FakeGCS
from unit.e_infra.conftest import gcs_args

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from pytest_httpserver import HTTPServer

### a port nothing listens on.
CLOSED = "http://127.0.0.1:9"


@pytest.fixture
async def down() -> AsyncIterator[GCSBlobDriver]:
    async with GCSBlobDriver(bucket="test-bucket", prefix="", api_root=CLOSED, timeout=2, page=10) as driver:
        yield driver


@pytest.fixture
async def refusing(httpserver: HTTPServer) -> AsyncIterator[GCSBlobDriver]:
    """GCS answering 500 to everything."""
    httpserver.expect_request(re.compile(".*")).respond_with_handler(FakeGCS(fail=500).serve)
    async with GCSBlobDriver(**gcs_args(api_root=httpserver.url_for("").rstrip("/"))) as driver:
        yield driver


async def drain(driver: GCSBlobDriver) -> list[Any]:
    return [each async for each in driver.list("x/")]


@pytest.mark.parametrize(
    "call",
    [
        lambda driver: driver.health(),
        lambda driver: driver.put("x", b"1"),
        lambda driver: driver.get("x"),
        lambda driver: driver.head("x"),
        drain,
    ],
    ids=["health", "put", "get", "head", "list"],
)
async def test_gcs_an_unreachable_bucket_is_a_blob_error(
    down: GCSBlobDriver, call: Callable[[GCSBlobDriver], Awaitable[Any]]
) -> None:
    with pytest.raises(BlobError):
        await call(down)


@pytest.mark.parametrize(
    "call",
    [
        lambda driver: driver.health(),
        lambda driver: driver.put("x", b"1"),
        lambda driver: driver.get("x"),
        lambda driver: driver.head("x"),
        drain,
    ],
    ids=["health", "put", "get", "head", "list"],
)
async def test_gcs_a_refusal_is_a_blob_error_with_its_status(
    refusing: GCSBlobDriver, call: Callable[[GCSBlobDriver], Awaitable[Any]]
) -> None:
    with pytest.raises(BlobError, match=r"500|refused"):
        await call(refusing)


async def test_gcs_a_driver_not_open_refuses() -> None:
    with pytest.raises(BlobError, match="not open"):
        await GCSBlobDriver(**gcs_args()).get("x")
