"""tests/unit/e_infra/providers/drivers: the localhost HTTP services (pytest-httpserver), `DOWN`, the asyncpg fake, and the test Postgres.

`stub` is a live service answering by (method, path), `http_server` one that answers like a small JSON API,
`docling_server` a docling-serve stand-in; none leaves the machine. `database` is this worker's own database beside
POSTGRES_TEST_DSN's, `pg` a psqlpy driver over a fresh `adapters` schema holding one probe table — the real-service
tests of the database and cache drivers run on them."""

import json
import re
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

import asyncpg
import pytest
import pytest_asyncio
from psqlpy.exceptions import Error as PsqlError
from pytest_httpserver import HTTPServer, RequestHandler
from werkzeug import Request, Response

from e_infra.infra.config.base import Secret
from e_infra.infra.config.providers.drivers.database.psqlpy import PsqlpySettings
from e_infra.providers.drivers.database.psqlpy import PsqlpyDriver
from e_infra.providers.drivers.http.wreq import WreqDriver
from support.asyncpg import FakeAsyncpgServer
from unit.e_infra.conftest import DSN, create

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Iterator

    from e_infra.ports.http import HttpPort

type Answer = tuple[int, bytes | Iterable[bytes]]


##### SERVER — one threaded localhost server per worker #####
@pytest.fixture(scope="session")
def make_httpserver() -> Iterator[HTTPServer]:
    """pytest-httpserver's own server, threaded: a handler that sleeps (a slow route) holds no other request."""
    server = HTTPServer(host="127.0.0.1", port=0, threaded=True)
    server.start()
    yield server
    server.clear()
    server.stop()


def respond(status: int, payload: bytes | Iterable[bytes], *, kind: str = "application/json") -> Response:
    """A bytes payload as one response, an iterable of bytes streamed — headers out first, frame by frame."""
    return Response(payload, status=status, content_type=kind)


##### STUB — a service answering by route #####
class StubRoutes:
    """The routes a stub knows; clearing them makes it answer nothing, as a server that went away."""

    def __init__(self, server: HTTPServer) -> None:
        self._server = server

    def clear(self) -> None:
        self._server.clear_all_handlers()


@dataclass(slots=True)
class Stub:
    """A live service on localhost, answering by (method, path); every request it took is kept, body decoded."""

    server: HTTPServer
    sent: list[tuple[str, str, dict[str, str], bytes]] = field(default_factory=list)
    known: dict[tuple[str, str | re.Pattern[str]], RequestHandler] = field(default_factory=dict)

    @property
    def url(self) -> str:
        return self.server.url_for("").rstrip("/")

    @property
    def routes(self) -> StubRoutes:
        return StubRoutes(self.server)

    def on(self, method: str, path: str | re.Pattern[str], answer: Callable[[bytes], Answer]) -> None:
        def serve(request: Request) -> Response:
            body = request.get_data()
            self.sent.append((request.method, request.path, {k.lower(): v for k, v in request.headers.items()}, body))
            status, payload = answer(body)
            return respond(status, payload)

        ### a route taught again is replaced, not stacked: the server answers with the first handler that matches.
        _ = (old := self.known.pop((method, path), None)) and self.server.handlers.remove(old)
        self.known[method, path] = self.server.expect_request(path, method=method)
        self.known[method, path].respond_with_handler(serve)

    def json(self, method: str, path: str, payload: object, status: int = 200) -> None:
        self.on(method, path, lambda _body: (status, json.dumps(payload).encode()))

    def bodies(self, path: str) -> list[bytes]:
        return [body for _method, where, _headers, body in self.sent if where == path]


@pytest.fixture
def stub(httpserver: HTTPServer) -> Stub:
    """A live service on localhost, no routes yet: tests teach it what to answer."""
    return Stub(httpserver)


@pytest.fixture
def http_server(stub: Stub) -> str:
    """A small JSON API: /ok answers, /slow answers late, a POST is echoed, anything else is a 500."""

    def slow(_body: bytes) -> Answer:
        time.sleep(1.0)
        return 200, b"{}"

    stub.json("GET", "/ok", {"hello": "world"})
    stub.on("GET", "/slow", slow)
    stub.on("POST", re.compile(".*"), lambda body: (200, body))
    stub.json("GET", "/boom", {"error": "boom"}, status=500)
    return stub.url


##### DOCLING — a docling-serve stand-in #####
@dataclass(slots=True)
class DoclingStub:
    """docling-serve as a test sees it: where it listens, the requests it took, the polls each task got.

    A source URL ending in `/fail` makes a failed task, `/slow` one that never settles, `/hang` a request that is not
    answered in time, `/stall` one whose headers arrive at once and whose body does not."""

    server: HTTPServer
    requests: list[dict[str, object]] = field(default_factory=list)
    polls: dict[str, int] = field(default_factory=dict)
    ready: bool = True

    @property
    def url(self) -> str:
        return self.server.url_for("").rstrip("/")

    @property
    def handler(self) -> DoclingStub:
        """Its recorded state — `polls`, `ready` — where a test reads and flips it."""
        return self

    @property
    def sent(self) -> dict[str, object]:
        """The last request body the server took."""
        return self.requests[-1]

    def post(self, request: Request) -> Response:
        body = json.loads(request.get_data())
        self.requests.append(body)
        source = body["sources"][0]
        task = str(source.get("url", "inline")).rpartition("/")[2]
        ### `/hang`: the server takes the request and never answers in time — the deadline must cut it.
        _ = time.sleep(1.0) if task == "hang" else None
        answer = json.dumps({"task_id": task, "task_type": "convert", "task_status": "pending"}).encode()
        return respond(200, self._late(answer) if task == "stall" else answer)

    @staticmethod
    def _late(answer: bytes) -> Iterator[bytes]:
        """Headers out at once, the body only after the deadline — the cut lands on the body read."""
        yield b""
        time.sleep(1.0)
        yield answer

    def get(self, request: Request) -> Response:
        match request.path.split("/"):
            case ["", "ready"]:
                return respond(200 if self.ready else 503, b'{"status": "ok"}')
            case ["", "v1", "status", "poll", task]:
                self.polls[task] = self.polls.get(task, 0) + 1
                settled = {"fail": "failure", "slow": "started"}.get(task, "success")
                state = "started" if self.polls[task] == 1 else settled
                status = {"task_id": task, "task_status": state, "error_message": "bad pdf" if task == "fail" else None}
                return respond(200, json.dumps(status).encode())
            case ["", "v1", "result", task]:
                document = {"filename": f"{task}.pdf", "md_content": "# Title", "json_content": {"tables": []}}
                result = {"document": document, "status": "success", "errors": [], "processing_time": 1.5}
                return respond(200, json.dumps(result).encode())
            case _:
                return respond(404, b'{"detail": "not found"}')


@pytest.fixture
def docling_server(httpserver: HTTPServer) -> DoclingStub:
    """A live docling-serve stand-in on localhost; its recorded requests and polls start empty in every test."""
    docling = DoclingStub(httpserver)
    httpserver.expect_request(re.compile(".*"), method="POST").respond_with_handler(docling.post)
    httpserver.expect_request(re.compile(".*"), method="GET").respond_with_handler(docling.get)
    return docling


##### HTTP #####
### a loopback port nothing listens on: a provider that is down, refused at once.
DOWN: Final[str] = "http://127.0.0.1:9"


@pytest.fixture
async def http() -> AsyncIterator[HttpPort]:
    """The process's HTTP driver, open, with no base: the drivers that ride it name absolute URLs."""
    async with WreqDriver() as driver:
        yield driver


##### ASYNCPG — a pool that holds no database #####
@pytest.fixture
def asyncpg_server(monkeypatch: pytest.MonkeyPatch) -> FakeAsyncpgServer:
    """The fake server `asyncpg.create_pool` and `asyncpg.connect` answer from, for the test's length."""
    server = FakeAsyncpgServer()
    monkeypatch.setattr(asyncpg, "create_pool", server.create_pool)
    monkeypatch.setattr(asyncpg, "connect", server.connect)
    return server


##### POSTGRES #####
@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def database(worker_id: str) -> str:
    """A database of the adapter tests' own beside POSTGRES_TEST_DSN's; every test needing it skips with no server."""
    try:
        return await create(f"{DSN}_adapters_{worker_id}")
    except PsqlError as error:
        pytest.skip(f"no test Postgres at {DSN.rpartition('@')[2]}: {error}")


@pytest.fixture
def pg_settings(database: str) -> PsqlpySettings:
    return PsqlpySettings(dsn=Secret(database), pool=2)


@pytest.fixture
async def pg(pg_settings: PsqlpySettings) -> AsyncIterator[PsqlpyDriver]:
    """A connected adapter over a fresh `adapters` schema holding one probe table, dropped after the test."""
    async with PsqlpyDriver(pg_settings) as adapter:
        await adapter.execute("CREATE EXTENSION IF NOT EXISTS vector")
        await adapter.execute("DROP SCHEMA IF EXISTS adapters CASCADE")
        await adapter.execute("CREATE SCHEMA adapters")
        await adapter.execute("CREATE TABLE adapters.probe (id int PRIMARY KEY, label text, v vector(3))")
        yield adapter
        await adapter.execute("DROP SCHEMA adapters CASCADE")
