"""tests/unit/e_core/adapters/http: wreq lifecycle offline, JSON roundtrip and typed decode against a real socket."""

import msgspec
import pytest
import wreq

from e_core.adapters.http import HttpAdapter
from e_core.core.settings.http import HttpSettings


class Greeting(msgspec.Struct, frozen=True):
    hello: str


async def test_http_adapter_lifecycle_needs_no_network() -> None:
    """wreq opens a pool, not a connection: the cycle is pure client construction and drop."""
    adapter = HttpAdapter(HttpSettings())
    async with adapter:
        assert adapter.name == "http"
    with pytest.raises(RuntimeError, match="not connected"):
        await adapter.get("/get")


async def test_http_roundtrip_and_status_error(http_server: str) -> None:
    """Real bytes over a real socket: decode on success, the library's own error on non-2xx, no-op close after."""
    adapter = HttpAdapter(HttpSettings(http_base_url=http_server))
    async with adapter:
        assert await adapter.get("/ok") == {"hello": "world"}
        assert await adapter.post("/echo", {"ping": 1}) == {"ping": 1}
        with pytest.raises(wreq.StatusError):
            await adapter.get("/bad")
    await adapter.close()  # the stack already closed it: second close is the None branch, not an error


async def test_http_get_decodes_typed_shape(http_server: str) -> None:
    """`as_` names the msgspec shape; the body arrives converted, not as a raw dict."""
    adapter = HttpAdapter(HttpSettings(http_base_url=http_server))
    async with adapter:
        assert await adapter.get("/ok", as_=Greeting) == Greeting(hello="world")


async def test_http_post_decodes_typed_shape(http_server: str) -> None:
    """The echo server returns the payload: post keeps the same typed-decode contract as get."""
    adapter = HttpAdapter(HttpSettings(http_base_url=http_server))
    async with adapter:
        assert await adapter.post("/echo", {"hello": "posted"}, as_=Greeting) == Greeting(hello="posted")
