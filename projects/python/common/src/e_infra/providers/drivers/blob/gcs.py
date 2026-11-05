"""providers/drivers/blob/gcs: GCS behind `BlobPort` — the JSON API through gcloud-aio-storage, ADC or the emulator.

A conditional write is GCS's own precondition (`ifGenerationMatch`): `0` creates only, a generation updates only while
it holds; its 412 is `BlobPreconditionError`, a 404 `BlobNotFoundError`, any other failure — no answer included —
`BlobError`. Keys live under GCS_PREFIX and come back without it. The driver owns its aiohttp session; on GCS its
token comes from ADC.

Chosen over obstore (Rust, object_store) by evidence: obstore speaks GCS's XML API and percent-encodes the `/` of a key,
which the emulator answers with 404 — no end-to-end test would run locally."""

from typing import TYPE_CHECKING, Any, ClassVar, Final, Self

import aiohttp
from gcloud.aio.storage import Storage

from e_infra.infra.errors import BlobError, BlobNotFoundError, BlobPreconditionError
from e_infra.infra.logger import logger
from e_infra.ports.blob import BlobMeta
from e_infra.ports.provider import Isolation, Locality, ProviderSpec, Workload

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

### what aiohttp raises when GCS refuses or does not answer: translated at the border, never past it.
FAILURES: Final[tuple[type[Exception], ...]] = (aiohttp.ClientError, TimeoutError)


class GCSBlobDriver:
    """One bucket, under one prefix, behind `BlobPort`."""

    spec: ClassVar[ProviderSpec] = ProviderSpec("gcs", Locality.REMOTE, Workload.IO_BOUND, Isolation.LOOP, pooled=True)

    __slots__ = ("_api_root", "_bucket", "_page", "_prefix", "_session", "_storage", "_timeout")

    def __init__(self, *, bucket: str, prefix: str, api_root: str | None, timeout: int, page: int) -> None:
        self._bucket, self._prefix, self._api_root, self._timeout, self._page = bucket, prefix, api_root, timeout, page
        self._session: aiohttp.ClientSession | None = None
        self._storage: Storage | None = None

    ##### PRIVATE #####

    def _common_storage(self) -> Storage:
        match self._storage:
            case None:
                msg = "GCSBlobDriver is not open: the lifespan opens it, callers never do"
                raise BlobError(msg)
            case storage:
                return storage

    def _common_meta(self, item: dict[str, Any]) -> BlobMeta:
        return BlobMeta(
            key=item["name"].removeprefix(self._prefix), generation=int(item["generation"]), size=int(item["size"])
        )

    def _common_error(self, key: str, error: Exception) -> BlobError:
        """GCS's answer — or its silence — as the port's error."""
        match error:
            case aiohttp.ClientResponseError(status=412):
                return BlobPreconditionError(f"{key}: another writer came first ({error.message})")
            case aiohttp.ClientResponseError(status=404):
                return BlobNotFoundError(key)
            case aiohttp.ClientResponseError(status=status):
                logger.error("gcs failed", key=key, status=status, error=error.message)
                return BlobError(f"{key}: GCS answered {status} ({error.message})")
            case _:
                logger.error("gcs unreachable", key=key, error=str(error))
                return BlobError(f"{key}: GCS did not answer ({type(error).__name__}: {error})")

    ############################################################

    ##### PUBLIC #####

    async def __aenter__(self) -> Self:
        self._session = aiohttp.ClientSession()
        self._storage = Storage(session=self._session, api_root=self._api_root)
        logger.info("gcs opened", bucket=self._bucket, prefix=self._prefix, emulator=self._api_root)
        return self

    async def __aexit__(self, *exc: object) -> None:
        session, self._session, self._storage = self._session, None, None
        _ = session is not None and await session.close()
        logger.info("gcs closed")

    async def health(self) -> bool:
        """The bucket answers a one-object listing: the credentials and the bucket at once."""
        try:
            await self._common_storage().list_objects(self._bucket, params={"maxResults": "1"}, timeout=self._timeout)
        except FAILURES as error:
            logger.warning("gcs unhealthy", bucket=self._bucket, error=str(error))
            raise BlobError(str(error)) from error
        return True

    async def put(self, key: str, data: bytes, *, if_generation: int | None = None) -> BlobMeta:
        """Write `data` at `key` — unconditionally, create-only (`0`), or while the generation read still holds."""
        condition = {} if if_generation is None else {"ifGenerationMatch": str(if_generation)}
        try:
            item = await self._common_storage().upload(
                self._bucket, f"{self._prefix}{key}", data, parameters=condition, timeout=self._timeout
            )
        except FAILURES as error:
            raise self._common_error(key, error) from error
        return self._common_meta(item)

    async def get(self, key: str) -> bytes:
        try:
            return await self._common_storage().download(self._bucket, f"{self._prefix}{key}", timeout=self._timeout)
        except FAILURES as error:
            raise self._common_error(key, error) from error

    async def head(self, key: str) -> BlobMeta | None:
        try:
            item = await self._common_storage().download_metadata(
                self._bucket, f"{self._prefix}{key}", timeout=self._timeout
            )
        except FAILURES as error:
            match self._common_error(key, error):
                case BlobNotFoundError():
                    return None
                case other:
                    raise other from error
        return self._common_meta(item)

    async def list(self, prefix: str) -> AsyncIterator[BlobMeta]:
        """Every object under `prefix`, a page at a time, as GCS hands them."""
        params = {"prefix": f"{self._prefix}{prefix}", "maxResults": str(self._page)}
        token: str | None = ""
        ### a real loop: pages are iteration over a cursor the server hands back one answer at a time.
        while token is not None:
            try:
                page = await self._common_storage().list_objects(
                    self._bucket, params=params | ({"pageToken": token} if token else {}), timeout=self._timeout
                )
            except FAILURES as error:
                raise self._common_error(prefix, error) from error
            for item in page.get("items", ()):
                yield self._common_meta(item)
            token = page.get("nextPageToken")
