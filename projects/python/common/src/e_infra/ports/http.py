"""ports/http: outbound HTTP — GET and POST of JSON, raw bytes, each bounded and optionally decoded to a shape."""

from typing import TYPE_CHECKING, Protocol, overload, runtime_checkable

from e_infra.ports.provider import Provider

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import timedelta


@runtime_checkable
class HttpPort(Provider, Protocol):
    """A path is joined to the configured base, an absolute URL goes as it is. A non-2xx answer raises `HttpError`, a
    request past its `within` (default the client's) raises `HttpTimeoutError`; `as_` names the msgspec shape the
    JSON body is converted to. `raw` is the GET whose body leaves undecoded."""

    @overload
    async def get[T](
        self, path: str, *, as_: type[T], within: timedelta | None = None, headers: Mapping[str, str] | None = None
    ) -> T: ...

    @overload
    async def get(
        self, path: str, *, as_: None = None, within: timedelta | None = None, headers: Mapping[str, str] | None = None
    ) -> object: ...

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

    async def raw(
        self, path: str, *, within: timedelta | None = None, headers: Mapping[str, str] | None = None
    ) -> bytes: ...
