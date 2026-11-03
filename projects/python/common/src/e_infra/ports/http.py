"""ports/http: outbound HTTP — GET, POST and DELETE of JSON, raw bytes, a streamed upload, each bounded."""

from typing import TYPE_CHECKING, Protocol, overload, runtime_checkable

from e_infra.ports.provider import Provider

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Mapping
    from datetime import timedelta


@runtime_checkable
class HTTPPort(Provider, Protocol):
    """A path is joined to the configured base, an absolute URL goes as it is. A non-2xx answer raises `HTTPError`, a
    request past its `within` (default the client's) raises `HTTPTimeoutError`; `as_` names the msgspec shape the
    JSON body is converted to. `raw` is the GET whose body leaves undecoded, `upload` the POST whose body is streamed,
    `delete` answers None for an empty body (204)."""

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

    async def upload(
        self,
        path: str,
        body: AsyncGenerator[bytes],
        *,
        within: timedelta | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> object: ...

    async def delete(
        self, path: str, *, within: timedelta | None = None, headers: Mapping[str, str] | None = None
    ) -> object: ...
