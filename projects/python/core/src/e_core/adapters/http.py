"""adapters/http: the external-service client on wreq (Rust wreq bindings, browser-fidelity TLS).

The third member of the adapter family: redis and sqlite speak KV, http speaks HTTP — all three
share the connect/close contract and are opened by the lifespan's AsyncExitStack."""

from typing import TYPE_CHECKING, ClassVar, overload

import msgspec
import wreq

from e_core.adapters.base import BaseAdapter
from e_core.core.settings import settings as st

if TYPE_CHECKING:
    from e_core.core.settings.http import HttpSettings


##### TYPES #####
class HttpAdapter(BaseAdapter):
    """One wreq client per app: base_url and timeout come from HttpSettings, responses leave as data."""

    name: ClassVar[str] = "http"

    def __init__(self, settings: HttpSettings | None = None) -> None:
        ### the default is read on call, not at import: the settings singleton stays lazy.
        conf = st.http if settings is None else settings
        self._base_url = conf.http_base_url
        self._timeout = conf.http_timeout
        self._client: wreq.Client | None = None

    ##### PRIVATE METHODS #####

    def _common_url(self, path: str) -> str:
        ### wreq 0.12 drops the client's base_url for relative paths (BadScheme): join here, one place, both verbs.
        return path if path.startswith(("http://", "https://")) else f"{self._base_url.rstrip('/')}/{path.lstrip('/')}"

    def _common_connected(self) -> wreq.Client:
        match self._client:
            case None:
                msg = "HttpAdapter not connected: the lifespan opens it, handlers never do"
                raise RuntimeError(msg)
            case client:
                return client

    @staticmethod
    def _common_decode[T](body: object, as_: type[T] | None) -> T | object:
        """The JSON body as-is, or converted to `as_` (msgspec, non-strict) when the caller names the shape."""
        return msgspec.convert(body, as_, strict=False) if as_ is not None else body

    ############################################################

    ##### PUBLIC #####

    async def connect(self) -> None:
        self._client = wreq.Client(timeout=self._timeout)

    async def close(self) -> None:
        match self._client:
            case None:
                return
            case client:
                ### sync in wreq: drops the Rust pool; our contract stays async.
                client.close()
                self._client = None

    @overload
    async def get[T](self, path: str, *, as_: type[T]) -> T: ...

    @overload
    async def get(self, path: str, *, as_: None = None) -> object: ...

    async def get[T](self, path: str, *, as_: type[T] | None = None) -> T | object:
        """GET against base_url; non-2xx raises the library's own StatusError, never a silent body."""
        response = await self._common_connected().get(self._common_url(path))
        response.raise_for_status()
        return self._common_decode(await response.json(), as_)

    @overload
    async def post[T](self, path: str, payload: object, *, as_: type[T]) -> T: ...

    @overload
    async def post(self, path: str, payload: object, *, as_: None = None) -> object: ...

    async def post[T](self, path: str, payload: object, *, as_: type[T] | None = None) -> T | object:
        """POST with a JSON payload; same raise-and-decode contract as get()."""
        response = await self._common_connected().post(self._common_url(path), json=payload)
        response.raise_for_status()
        return self._common_decode(await response.json(), as_)
