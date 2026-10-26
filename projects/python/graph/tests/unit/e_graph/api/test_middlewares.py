"""tests/unit: api.middlewares — the CORS translation resolves settings at call time, never at import."""

from typing import TYPE_CHECKING, cast

from e_graph.api.middlewares import AccessLogMiddleware, cors_config
from infra.settings.api import ApiSettings, HttpMethod

if TYPE_CHECKING:
    from litestar.types import Receive, Scope, Send


def test_cors_config_reads_the_singleton_when_no_settings_given() -> None:
    config = cors_config()
    assert config.allow_origins == ["*"]


def test_cors_config_honours_explicit_settings() -> None:
    config = cors_config(ApiSettings(allow_origins=["https://eager.test"], allow_methods=[HttpMethod.GET]))
    assert config.allow_origins == ["https://eager.test"]
    assert config.allow_methods == ["GET"]


async def test_access_log_passes_non_http_scopes_through() -> None:
    seen: list[str] = []

    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append(scope["type"])

    async def receive() -> object: ...

    async def send(message: object) -> None: ...

    await AccessLogMiddleware(inner)(cast("Scope", {"type": "websocket"}), cast("Receive", receive), cast("Send", send))
    assert seen == ["websocket"]
