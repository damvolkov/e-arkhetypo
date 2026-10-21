"""tests/unit/e_core/adapters: the http and docling harnesses — real stdlib sockets on localhost, offline-safe — and
the awa and postgres adapters on the test Postgres."""

import asyncio
import json
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING, ClassVar, Final

import pytest
import pytest_asyncio
from psqlpy.exceptions import Error as PsqlError

from e_core.adapters.awa import AwaAdapter
from e_core.adapters.base import BaseAdapter
from e_core.adapters.postgres import PostgresAdapter
from e_core.conftest import DSN, create
from e_core.core.settings.base import Secret
from e_core.core.settings.postgres import PostgresSettings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

    from e_core.core.settings.queue import QueueSettings


class JsonHandler(BaseHTTPRequestHandler):
    """Answers /ok with a JSON body, echoes POST payloads, 500 on everything else."""

    def do_GET(self) -> None:
        self._respond(200, b'{"hello": "world"}') if self.path == "/ok" else self._respond(500, b'{"error": "boom"}')

    def do_POST(self) -> None:
        self._respond(200, self.rfile.read(int(self.headers["content-length"])))  # echo the payload

    def _respond(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 — name imposed by http.server
        """Quiet: http.server's per-request stderr noise stays out of the test output."""


@pytest.fixture
def http_server() -> Iterator[str]:
    """A live base_url served from a daemon thread, shut down with the test."""
    with ThreadingHTTPServer(("127.0.0.1", 0), JsonHandler) as srv:
        worker = threading.Thread(target=srv.serve_forever, daemon=True)
        worker.start()
        yield f"http://127.0.0.1:{srv.server_port}"
        srv.shutdown()
        worker.join()


class DoclingHandler(BaseHTTPRequestHandler):
    """A docling-serve stand-in: async tasks that start, then settle; the last request kept for inspection.

    A source URL ending in `/fail` makes a failed task, `/slow` one that never settles, `/hang` a request
    that is not answered in time."""

    requests: ClassVar[list[dict[str, object]]] = []
    polls: ClassVar[dict[str, int]] = {}
    ready: ClassVar[bool] = True

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        DoclingHandler.requests.append(body)
        source = body["sources"][0]
        task = str(source.get("url", "inline")).rpartition("/")[2]
        ### `/hang`: the server takes the request and never answers in time — the deadline must cut it.
        _ = time.sleep(1.0) if task == "hang" else None
        self._respond(200, {"task_id": task, "task_type": "convert", "task_status": "pending"})

    def do_GET(self) -> None:
        path, _, _ = self.path.partition("?")
        match path.split("/"):
            case ["", "ready"]:
                self._respond(200 if DoclingHandler.ready else 503, {"status": "ok"})
            case ["", "v1", "status", "poll", task]:
                DoclingHandler.polls[task] = DoclingHandler.polls.get(task, 0) + 1
                settled = {"fail": "failure", "slow": "started"}.get(task, "success")
                state = "started" if DoclingHandler.polls[task] == 1 else settled
                self._respond(
                    200, {"task_id": task, "task_status": state, "error_message": "bad pdf" if task == "fail" else None}
                )
            case ["", "v1", "result", task]:
                document = {"filename": f"{task}.pdf", "md_content": "# Title", "json_content": {"tables": []}}
                self._respond(200, {"document": document, "status": "success", "errors": [], "processing_time": 1.5})
            case _:
                self._respond(404, {"detail": "not found"})

    def _respond(self, status: int, payload: object) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 — name imposed by http.server
        """Quiet."""


@dataclass(frozen=True, slots=True)
class DoclingStub:
    """The stand-in as a test sees it: where it listens, and its handler's recorded state."""

    url: str
    handler: type[DoclingHandler]

    @property
    def sent(self) -> dict[str, object]:
        """The last request body the server took."""
        return self.handler.requests[-1]


@pytest.fixture
def docling_server() -> Iterator[DoclingStub]:
    """A live docling-serve stand-in on localhost; its recorded requests and polls reset per test."""
    DoclingHandler.requests.clear()
    DoclingHandler.polls.clear()
    DoclingHandler.ready = True
    with ThreadingHTTPServer(("127.0.0.1", 0), DoclingHandler) as srv:
        worker = threading.Thread(target=srv.serve_forever, daemon=True)
        worker.start()
        yield DoclingStub(url=f"http://127.0.0.1:{srv.server_port}", handler=DoclingHandler)
        srv.shutdown()


##### PING #####
### a loopback port nothing listens on: a provider that is down, refused at once.
DOWN: Final[str] = "http://127.0.0.1:9"


class StubAdapter(BaseAdapter):
    """An adapter whose provider answers its ping after `delay` seconds, or fails it with `down`."""

    name: ClassVar[str] = "stub"

    def __init__(self, delay: float = 0.0, down: BaseException | None = None) -> None:
        self.delay, self.down = delay, down

    async def connect(self) -> None:
        """Nothing to open."""

    async def close(self) -> None:
        """Nothing to release."""

    async def ping(self) -> None:
        await asyncio.sleep(self.delay)
        match self.down:
            case None:
                return
            case error:
                raise error


##### QUEUE #####
@pytest.fixture
async def awa(queue_settings: QueueSettings) -> AsyncIterator[AwaAdapter]:
    async with AwaAdapter(queue_settings) as adapter:
        yield adapter


##### POSTGRES #####
@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def database(worker_id: str) -> str:
    """A database of the adapter tests' own beside POSTGRES_TEST_DSN's; every test needing it skips with no server."""
    try:
        return await create(f"{DSN}_adapters_{worker_id}")
    except PsqlError as error:
        pytest.skip(f"no test Postgres at {DSN.rpartition('@')[2]}: {error}")


@pytest.fixture
def pg_settings(database: str) -> PostgresSettings:
    return PostgresSettings(dsn=Secret(database), pool=2)


@pytest.fixture
async def pg(pg_settings: PostgresSettings) -> AsyncIterator[PostgresAdapter]:
    """A connected adapter over a fresh `adapters` schema holding one probe table, dropped after the test."""
    async with PostgresAdapter(pg_settings) as adapter:
        await adapter.execute("CREATE EXTENSION IF NOT EXISTS vector")
        await adapter.execute("DROP SCHEMA IF EXISTS adapters CASCADE")
        await adapter.execute("CREATE SCHEMA adapters")
        await adapter.execute("CREATE TABLE adapters.probe (id int PRIMARY KEY, label text, v vector(3))")
        yield adapter
        await adapter.execute("DROP SCHEMA adapters CASCADE")
