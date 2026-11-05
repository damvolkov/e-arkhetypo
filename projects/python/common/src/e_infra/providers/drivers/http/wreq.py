"""providers/drivers/http/wreq: the outbound client on wreq (Rust wreq bindings, browser-fidelity TLS).

One client per process, opened by the lifespan. The other drivers that speak HTTP (docling, TEI, an OpenAI-compatible
server) receive it as an `HTTPPort` and name absolute URLs, so the process holds one connection pool, not one per
service. Every request carries HTTP_AGENT as its User-Agent and HTTP_HEADERS; a call's own `headers` go over them for
that request only — a service's credential travels there, never in the shared client. wreq's errors are `HTTPError` from here up: a non-2xx answer carries its `status`, a request past its bound is
an `HTTPTimeoutError` — the bound covers the body too, where wreq says `BodyError` with a `TimedOut` source."""

from contextlib import contextmanager
from operator import methodcaller
from typing import TYPE_CHECKING, Any, ClassVar, Final, Self, overload

import msgspec
import wreq

from e_infra.infra.errors import HTTPError, HTTPTimeoutError, ProviderError
from e_infra.infra.logger import logger
from e_infra.ports.provider import Isolation, Locality, ProviderSpec, Workload

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable, Generator, Mapping
    from datetime import timedelta

    from pydantic import HttpUrl

TIMED_OUT: Final = "TimedOut"
WIRE: Final = (
    wreq.BodyError,
    wreq.BuilderError,
    wreq.ConnectionError,
    wreq.ConnectionResetError,
    wreq.DecodingError,
    wreq.ProxyConnectionError,
    wreq.RedirectError,
    wreq.RequestError,
    wreq.TlsError,
)


##### TYPES #####
class WreqDriver:
    """One wreq client per process: base_url and timeout are given, responses leave as data."""

    spec: ClassVar[ProviderSpec] = ProviderSpec("wreq", Locality.REMOTE, Workload.IO_BOUND, Isolation.LOOP, pooled=True)

    def __init__(self, *, base_url: HttpUrl, timeout: timedelta, agent: str, headers: Mapping[str, str]) -> None:
        self._base_url = str(base_url)
        self._timeout = timeout
        self._headers = {"User-Agent": agent, **headers}
        self._client: wreq.Client | None = None

    ##### PRIVATE METHODS #####

    def _common_url(self, path: str) -> str:
        ### wreq 0.12 drops the client's base_url for relative paths (BadScheme): join here, one place, every verb.
        return path if path.startswith(("http://", "https://")) else f"{self._base_url.rstrip('/')}/{path.lstrip('/')}"

    def _common_open(self) -> wreq.Client:
        match self._client:
            case None:
                msg = "WreqDriver is not open: the lifespan opens it, handlers never do"
                raise HTTPError(msg)
            case client:
                return client

    @staticmethod
    @contextmanager
    def _common_guard() -> Generator[None]:
        """wreq's own errors, as the tree's `HTTPError` — a timeout as `HTTPTimeoutError`."""
        try:
            yield
        except wreq.TimeoutError as error:
            logger.error("wreq timed out", error=str(error))
            raise HTTPTimeoutError(str(error)) from error
        except wreq.BodyError as error:
            logger.error("wreq body failed", error=str(error))
            match TIMED_OUT in str(error):
                case True:
                    raise HTTPTimeoutError(str(error)) from error
                case _:
                    raise HTTPError(str(error)) from error
        except WIRE as error:
            logger.error("wreq failed", error=str(error))
            raise HTTPError(str(error)) from error

    @staticmethod
    def _common_decode[T](body: object, as_: type[T] | None) -> T | object:
        """The JSON body as-is, or converted to `as_` (msgspec, non-strict) when the caller names the shape."""
        try:
            return msgspec.convert(body, as_, strict=False) if as_ is not None else body
        except msgspec.ValidationError as error:
            msg = f"the body is not a {as_}: {error}"
            raise HTTPError(msg) from error

    async def _common_send[R](
        self,
        read: Callable[[wreq.Response], Awaitable[R]],
        method: str,
        path: str,
        *,
        within: timedelta | None,
        headers: Mapping[str, str] | None,
        **body: object,
    ) -> R:
        """One request, its answer read; any 2xx, else `HTTPError` with the status. `body` is the verb's own: `json`, or
        a streamed `body`."""
        client, url = self._common_open(), self._common_url(path)
        logger.debug("wreq request", method=method.upper(), url=url)
        options: dict[str, Any] = {
            key: value for key, value in {"timeout": within, "headers": headers and dict(headers)}.items() if value
        }
        with self._common_guard():
            response = await getattr(client, method)(url, **body, **options)
            match response.status.is_success():
                case True:
                    answer = await read(response)
                case _:
                    status = response.status.as_int()
                    msg = f"{url} answered {status}"
                    logger.error("wreq refused", url=url, status=status)
                    raise HTTPError(msg, status)
        return answer

    @staticmethod
    async def _delete_read(response: wreq.Response) -> object:
        """A DELETE's answer: its JSON, or None for an empty body (204)."""
        raw = await response.bytes()
        return msgspec.json.decode(raw) if raw else None

    ############################################################

    ##### PUBLIC #####

    async def __aenter__(self) -> Self:
        self._client = wreq.Client(timeout=self._timeout, headers=self._headers)
        logger.info("wreq opened", base_url=self._base_url)
        return self

    async def __aexit__(self, *exc: object) -> None:
        match self._client:
            case None:
                return
            case client:
                ### sync in wreq: drops the Rust pool; our contract stays async.
                client.close()
                self._client = None
                logger.info("wreq closed")

    async def health(self) -> bool:
        """The client is open: its base is anyone's service, never a dependency to probe."""
        try:
            self._common_open()
        except ProviderError as error:
            logger.warning("wreq unhealthy", error=str(error))
            raise
        return True

    @overload
    async def get[T](
        self, path: str, *, as_: type[T], within: timedelta | None = None, headers: Mapping[str, str] | None = None
    ) -> T: ...

    @overload
    async def get(
        self, path: str, *, as_: None = None, within: timedelta | None = None, headers: Mapping[str, str] | None = None
    ) -> object: ...

    async def get[T](
        self,
        path: str,
        *,
        as_: type[T] | None = None,
        within: timedelta | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> T | object:
        """GET: the JSON body, decoded to `as_` when named; non-2xx raises `HTTPError`, never a silent body."""
        body = await self._common_send(methodcaller("json"), "get", path, within=within, headers=headers)
        return self._common_decode(body, as_)

    @overload
    async def post[T](
        self,
        path: str,
        payload: object,
        *,
        as_: type[T],
        within: timedelta | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> T: ...

    @overload
    async def post(
        self,
        path: str,
        payload: object,
        *,
        as_: None = None,
        within: timedelta | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> object: ...

    async def post[T](
        self,
        path: str,
        payload: object,
        *,
        as_: type[T] | None = None,
        within: timedelta | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> T | object:
        """POST with a JSON payload; same raise-and-decode contract as get()."""
        body = await self._common_send(methodcaller("json"), "post", path, within=within, headers=headers, json=payload)
        return self._common_decode(body, as_)

    async def raw(
        self, path: str, *, within: timedelta | None = None, headers: Mapping[str, str] | None = None
    ) -> bytes:
        """GET whose body leaves undecoded."""
        return bytes(await self._common_send(methodcaller("bytes"), "get", path, within=within, headers=headers))

    async def upload(
        self,
        path: str,
        body: AsyncGenerator[bytes],
        *,
        within: timedelta | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> object:
        """POST a body streamed as it is produced — a file never held whole —; the JSON answer, same raise contract."""
        return await self._common_send(methodcaller("json"), "post", path, within=within, headers=headers, body=body)

    async def delete(
        self, path: str, *, within: timedelta | None = None, headers: Mapping[str, str] | None = None
    ) -> object:
        """DELETE: the JSON answer, or None for an empty one (204); same raise contract as get()."""
        return await self._common_send(self._delete_read, "delete", path, within=within, headers=headers)
