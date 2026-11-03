"""e_infra/providers/drivers/http/wreq: wreq lifecycle offline, JSON roundtrip, typed decode and the error border."""

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING

import msgspec
import pytest

from e_infra.infra.config.providers.drivers.http.wreq import WreqSettings
from e_infra.infra.errors import HttpError, HttpTimeoutError
from e_infra.ports.http import HttpPort
from e_infra.providers.drivers.http.wreq import WreqDriver

if TYPE_CHECKING:
    from unit.e_infra.conftest import Logs


class Greeting(msgspec.Struct, frozen=True):
    hello: str


async def test_http_adapter_lifecycle_needs_no_network() -> None:
    """wreq opens a pool, not a connection: the cycle is pure client construction and drop."""
    adapter = WreqDriver(WreqSettings())
    async with adapter:
        assert isinstance(adapter, HttpPort)
    with pytest.raises(HttpError, match="not open"):
        await adapter.get("/get")


async def test_http_roundtrip_and_status_error(http_server: str) -> None:
    """Real bytes over a real socket: decode on success, the library's own error on non-2xx, no-op close after."""
    adapter = WreqDriver(WreqSettings(base_url=http_server))
    async with adapter:
        assert await adapter.get("/ok") == {"hello": "world"}
        assert await adapter.post("/echo", {"ping": 1}) == {"ping": 1}
        with pytest.raises(HttpError) as caught:
            await adapter.get("/bad")
    assert caught.value.status == 500
    await adapter.__aexit__(None, None, None)  # the stack already closed it: second exit is a no-op, not an error


async def test_http_get_decodes_typed_shape(http_server: str) -> None:
    """`as_` names the msgspec shape; the body arrives converted, not as a raw dict."""
    adapter = WreqDriver(WreqSettings(base_url=http_server))
    async with adapter:
        assert await adapter.get("/ok", as_=Greeting) == Greeting(hello="world")


async def test_http_post_decodes_typed_shape(http_server: str) -> None:
    """The echo server returns the payload: post keeps the same typed-decode contract as get."""
    adapter = WreqDriver(WreqSettings(base_url=http_server))
    async with adapter:
        assert await adapter.post("/echo", {"hello": "posted"}, as_=Greeting) == Greeting(hello="posted")


async def test_http_raw_headers_and_timeout(http_server: str) -> None:
    """`raw` leaves the body undecoded; headers and a per-request bound travel; a bound passed is a timeout."""
    async with WreqDriver(WreqSettings(base_url=http_server)) as adapter:
        assert await adapter.raw("/ok", headers={"x-test": "1"}) == b'{"hello": "world"}'
        with pytest.raises(HttpTimeoutError):
            await adapter.get("/slow", within=timedelta(milliseconds=50))


async def test_http_body_shape_mismatch(http_server: str) -> None:
    """A body that is not the named shape is an `HttpError`, not msgspec's."""
    async with WreqDriver(WreqSettings(base_url=http_server)) as adapter:
        with pytest.raises(HttpError, match="not a"):
            await adapter.get("/ok", as_=list[int])


async def test_http_unreachable() -> None:
    async with WreqDriver(WreqSettings(base_url="http://127.0.0.1:9")) as adapter:
        with pytest.raises(HttpError):
            await adapter.get("/x")


async def test_http_health() -> None:
    """The client is open: its base is anyone's service, never a dependency to probe — no network either way."""
    adapter = WreqDriver(WreqSettings(base_url="http://127.0.0.1:9"))
    async with adapter:
        assert await adapter.health()
    assert not await adapter.health()


async def test_http_lifecycle_is_logged(http_server: str, logs: Logs) -> None:
    async with WreqDriver(WreqSettings(base_url=http_server)):
        pass
    assert logs.at("info") == ["wreq opened", "wreq closed"]


async def test_http_a_refused_status_a_timeout_and_a_dead_server_are_logged_where_translated(
    http_server: str, logs: Logs
) -> None:
    async with WreqDriver(WreqSettings(base_url=http_server)) as adapter:
        with pytest.raises(HttpError):
            await adapter.get("/boom")
        with pytest.raises(HttpTimeoutError):
            await adapter.get("/slow", within=timedelta(milliseconds=50))
    async with WreqDriver(WreqSettings(base_url="http://127.0.0.1:9")) as dead:
        with pytest.raises(HttpError):
            await dead.get("/x")
    assert logs.at("error") == ["wreq refused", "wreq timed out", "wreq failed"]
    assert logs.at("debug") == ["wreq request"] * 3


async def test_http_unhealthy_is_warned_and_an_unopened_call_is_not_translated(logs: Logs) -> None:
    assert not await WreqDriver(WreqSettings()).health()
    assert logs.at("warning") == ["wreq unhealthy"]


async def test_http_a_cancelled_request_stays_a_cancellation_never_an_http_error(http_server: str) -> None:
    """wreq's Rust future surfaces a cancel as a bare CancelledError: the border neither swallows nor translates it."""
    async with WreqDriver(WreqSettings(base_url=http_server)) as adapter:
        request = asyncio.ensure_future(adapter.get("/slow"))
        await asyncio.sleep(0.1)
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request
