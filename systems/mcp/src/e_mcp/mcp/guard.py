"""e_mcp.mcp.guard: the bearer gate in front of the MCP app — loopback is the wall, the token the door."""

import hmac
from typing import Any

from beartype import beartype

type Scope = dict[str, Any]
type Asgi = Any


@beartype
class TokenGuard:
    """ASGI middleware: an HTTP request without `Authorization: Bearer <token>` gets 401; lifespan passes."""

    __slots__ = ("_app", "_expected")

    def __init__(self, app: Asgi, token: str) -> None:
        self._app = app
        self._expected = f"Bearer {token}".encode()

    ##### PRIVATE METHODS #####

    def _call_admits(self, scope: Scope) -> bool:
        headers = dict(scope.get("headers", ()))
        return hmac.compare_digest(headers.get(b"authorization", b""), self._expected)

    @staticmethod
    async def _call_refuse(send: Asgi) -> None:
        await send({"type": "http.response.start", "status": 401, "headers": [(b"content-type", b"text/plain")]})
        await send({"type": "http.response.body", "body": b"unauthorized"})

    ############################################################

    ##### PUBLIC #####

    async def __call__(self, scope: Scope, receive: Asgi, send: Asgi) -> None:
        admitted = scope["type"] != "http" or self._call_admits(scope)
        await (self._app(scope, receive, send) if admitted else self._call_refuse(send))
