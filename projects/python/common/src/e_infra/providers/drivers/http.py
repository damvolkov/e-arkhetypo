"""providers/drivers/http: the outbound client on wreq (Rust wreq bindings, browser-fidelity TLS).

One client per process, opened by the lifespan. The other drivers that speak HTTP (docling, TEI, an OpenAI-compatible
server) receive it as an `HttpPort` and name absolute URLs, so the process holds one connection pool, not one per
service. wreq's errors are `HttpError` from here up: a non-2xx answer carries its `status`, a request past its bound is
an `HttpTimeoutError` — the bound covers the body too, where wreq says `BodyError` with a `TimedOut` source."""

from contextlib import contextmanager
from operator import methodcaller
from typing import TYPE_CHECKING, Any, ClassVar, Final, Self, overload

import msgspec
import wreq

from e_infra.infra.errors import HttpError, HttpTimeoutError, ProviderError
from e_infra.infra.settings import settings as st
from e_infra.ports.provider import Isolation, Locality, ProviderSpec, Workload

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Generator, Mapping
    from datetime import timedelta

    from e_infra.infra.config.http import HttpSettings

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
class HttpDriver:
    """One wreq client per process: base_url and timeout come from HttpSettings, responses leave as data."""

    spec: ClassVar[ProviderSpec] = ProviderSpec("http", Locality.REMOTE, Workload.IO_BOUND, Isolation.LOOP, pooled=True)

    def __init__(self, settings: HttpSettings | None = None) -> None:
        ### the default is read on call, not at import: the settings singleton stays lazy.
        conf = st.http if settings is None else settings
        self._base_url = conf.http_base_url
        self._timeout = conf.http_timeout
        self._client: wreq.Client | None = None

    ##### PRIVATE METHODS #####

    def _common_url(self, path: str) -> str:
        ### wreq 0.12 drops the client's base_url for relative paths (BadScheme): join here, one place, every verb.
        return path if path.startswith(("http://", "https://")) else f"{self._base_url.rstrip('/')}/{path.lstrip('/')}"

    def _common_open(self) -> wreq.Client:
        match self._client:
            case None:
                msg = "HttpDriver is not open: the lifespan opens it, handlers never do"
                raise HttpError(msg)
            case client:
                return client

    @staticmethod
    @contextmanager
    def _common_guard() -> Generator[None]:
        """wreq's own errors, as the tree's `HttpError` — a timeout as `HttpTimeoutError`."""
        try:
            yield
        except wreq.TimeoutError as error:
            raise HttpTimeoutError(str(error)) from error
        except wreq.BodyError as error:
            match TIMED_OUT in str(error):
                case True:
                    raise HttpTimeoutError(str(error)) from error
                case False:
                    raise HttpError(str(error)) from error
        except WIRE as error:
            raise HttpError(str(error)) from error

    @staticmethod
    def _common_decode[T](body: object, as_: type[T] | None) -> T | object:
        """The JSON body as-is, or converted to `as_` (msgspec, non-strict) when the caller names the shape."""
        try:
            return msgspec.convert(body, as_, strict=False) if as_ is not None else body
        except msgspec.ValidationError as error:
            msg = f"the body is not a {as_}: {error}"
            raise HttpError(msg) from error

    async def _common_send[R](
        self,
        read: Callable[[wreq.Response], Awaitable[R]],
        path: str,
        *,
        within: timedelta | None,
        headers: Mapping[str, str] | None,
        post: bool = False,
        payload: object = None,
    ) -> R:
        """One request, its answer read; any 2xx, else `HttpError` with the status."""
        client, url = self._common_open(), self._common_url(path)
        options: dict[str, Any] = {
            key: value for key, value in {"timeout": within, "headers": headers and dict(headers)}.items() if value
        }
        with self._common_guard():
            response = await (client.post(url, json=payload, **options) if post else client.get(url, **options))
            match response.status.is_success():
                case True:
                    body = await read(response)
                case False:
                    status = response.status.as_int()
                    msg = f"{url} answered {status}"
                    raise HttpError(msg, status)
        return body

    ############################################################

    ##### PUBLIC #####

    async def __aenter__(self) -> Self:
        self._client = wreq.Client(timeout=self._timeout)
        return self

    async def __aexit__(self, *exc: object) -> None:
        match self._client:
            case None:
                return
            case client:
                ### sync in wreq: drops the Rust pool; our contract stays async.
                client.close()
                self._client = None

    async def health(self) -> bool:
        """The client is open: its base is anyone's service, never a dependency to probe."""
        try:
            self._common_open()
        except ProviderError:
            return False
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
        """GET: the JSON body, decoded to `as_` when named; non-2xx raises `HttpError`, never a silent body."""
        body = await self._common_send(methodcaller("json"), path, within=within, headers=headers)
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
        body = await self._common_send(
            methodcaller("json"), path, post=True, payload=payload, within=within, headers=headers
        )
        return self._common_decode(body, as_)

    async def raw(
        self, path: str, *, within: timedelta | None = None, headers: Mapping[str, str] | None = None
    ) -> bytes:
        """GET whose body leaves undecoded."""
        return bytes(await self._common_send(methodcaller("bytes"), path, within=within, headers=headers))
