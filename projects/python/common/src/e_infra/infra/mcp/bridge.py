"""infra/mcp/bridge: a tool call as one request to the app itself — in process, through its middleware and guards.

The call passes its dependencies, its validation and its exception handlers, exactly as any route is served.

The request is born from the MCP endpoint's own: its `user` (the token middleware resolved it there, once), its server
and client, its correlation id; the arguments its JSON body; the guard's mark in its scope, which no client can send.
A 2xx answer is the tool's text and, when an object, its value — a list is wrapped as `result`, as the protocol wants
an object; a refusal is the route's own `detail`, or the arguments its validation named."""

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from e_infra.infra.logger import logger
from e_infra.infra.mcp.guard import MARK
from e_infra.infra.mcp.models import MCPAnswer

if TYPE_CHECKING:
    from collections.abc import Mapping

    from starlette.types import Message, Scope

    from e_infra.infra.payload import JSON

### the request headers carried over from the endpoint's request: its correlation, for one trace of a call.
CARRIED: Final[frozenset[bytes]] = frozenset({b"x-request-id"})
REFUSED: Final[int] = 400


@dataclass(slots=True)
class BridgeReply:
    """What the app answered, as its messages arrive: the status of the start, the body chunks joined."""

    status: int = 500
    body: bytes = b""


class MCPBridge:
    """Tool calls as in-process requests to the app that serves the MCP endpoint."""

    __slots__ = ()

    ##### PRIVATE #####

    @staticmethod
    def _call_scope(outer: Scope, path: str, body: bytes) -> Scope:
        carried = [(key, value) for key, value in outer.get("headers", ()) if key in CARRIED]
        return {
            "type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"}, "http_version": "1.1",
            "method": "POST", "scheme": outer.get("scheme", "http"), "path": path, "raw_path": path.encode(),
            "root_path": "", "query_string": b"", "server": outer.get("server"), "client": outer.get("client"),
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()), *carried],
            "user": outer.get("user"), "auth": None, "state": {}, MARK: True,
        }  # fmt: skip

    @staticmethod
    def _call_refusal(text: str) -> str:
        """The route's `detail`, and each field the validation named."""
        match text.startswith("{"):
            case False:
                return text
            case _:
                found = json.loads(text)
                fields = found.get("extra") or ()
                named = "; ".join(f"{each.get('key', '')}: {each.get('message', '')}" for each in fields)
                ### a validation names the route it failed on — the engine's business, not the agent's: the fields say it all.
                return f"invalid arguments: {named}" if named else str(found.get("detail", text))

    ############################################################

    ##### PUBLIC #####

    async def call(self, outer: Scope, path: str, arguments: Mapping[str, JSON]) -> MCPAnswer:
        """The answer of the tool's route to `arguments`, asked as the endpoint's caller."""
        body = json.dumps(dict(arguments)).encode()
        answered = BridgeReply()

        async def receive() -> Message:
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message: Message) -> None:
            ### the start carries the status, each body message a chunk; any other message carries neither.
            match message:
                case {"type": "http.response.start", "status": int() as status}:
                    answered.status = status
                case {"type": "http.response.body", "body": bytes() as chunk}:
                    answered.body += chunk
                case _:
                    pass

        await outer["app"](self._call_scope(outer, path, body), receive, send)
        text = answered.body.decode()
        logger.debug("mcp bridge call", path=path, status=answered.status)
        match answered.status >= REFUSED:
            case True:
                return MCPAnswer(text=self._call_refusal(text), error=True)
            case _:
                value = json.loads(text) if text else None
                return MCPAnswer(text=text, value=value if isinstance(value, dict) else {"result": value})
