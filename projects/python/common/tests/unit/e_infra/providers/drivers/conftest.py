"""tests/unit/e_infra/providers/drivers: the http and docling harnesses — real stdlib sockets on localhost, offline-safe —
and the queue drivers (awa, PgQueuer) and the postgres driver on the test Postgres. `port` is either durable queue,
unentered, for the contract both hold; `Flaky` and `Hang` are scripted handlers."""

import json
import threading
import time
from dataclasses import dataclass, field
from datetime import timedelta
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING, ClassVar, Final

import anyio
import pytest
import pytest_asyncio
from awa import AsyncClient
from psqlpy.exceptions import Error as PsqlError

from e_infra.infra.config.base import Secret
from e_infra.infra.config.postgres import PostgresSettings
from e_infra.providers.drivers.awa import AwaDriver
from e_infra.providers.drivers.http import HttpDriver
from e_infra.providers.drivers.pgqueuer import PgqueuerDriver
from e_infra.providers.drivers.postgres import PostgresDriver
from unit.e_infra.conftest import DSN, admin, create

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Iterator

    from e_infra.infra.background import BackgroundHandler, BackgroundRun
    from e_infra.infra.config.queue import QueueSettings
    from e_infra.ports.http import HttpPort


class JsonHandler(BaseHTTPRequestHandler):
    """Answers /ok with a JSON body, /slow late, echoes POST payloads, 500 on everything else."""

    def do_GET(self) -> None:
        match self.path:
            case "/ok":
                self._respond(200, b'{"hello": "world"}')
            case "/slow":
                time.sleep(1.0)
                self._respond(200, b"{}")
            case _:
                self._respond(500, b'{"error": "boom"}')

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
        worker = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        worker.start()
        yield f"http://127.0.0.1:{srv.server_port}"
        srv.shutdown()
        worker.join()


class DoclingHandler(BaseHTTPRequestHandler):
    """A docling-serve stand-in: async tasks that start, then settle; the last request kept for inspection.

    A source URL ending in `/fail` makes a failed task, `/slow` one that never settles, `/hang` a request
    that is not answered in time, `/stall` one whose headers arrive at once and whose body does not."""

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
        self._respond(200, {"task_id": task, "task_type": "convert", "task_status": "pending"}, stall=task == "stall")

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

    def _respond(self, status: int, payload: object, *, stall: bool = False) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        ### `stall`: headers out at once, the body only after the deadline — the cut lands on the body read.
        _ = (self.wfile.flush(), time.sleep(1.0)) if stall else None
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
        worker = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        worker.start()
        yield DoclingStub(url=f"http://127.0.0.1:{srv.server_port}", handler=DoclingHandler)
        srv.shutdown()


##### STUB — a service answering by route #####
@dataclass(slots=True)
class Stub:
    """A live service on localhost, answering by (method, path); every request it took is kept, body decoded."""

    url: str = ""
    routes: dict[tuple[str, str], Callable[[bytes], tuple[int, bytes]]] = field(default_factory=dict)
    sent: list[tuple[str, str, dict[str, str], bytes]] = field(default_factory=list)

    def on(self, method: str, path: str, answer: Callable[[bytes], tuple[int, bytes]]) -> None:
        self.routes[(method, path)] = answer

    def json(self, method: str, path: str, payload: object, status: int = 200) -> None:
        self.on(method, path, lambda _body: (status, json.dumps(payload).encode()))

    def bodies(self, path: str) -> list[bytes]:
        return [body for _method, where, _headers, body in self.sent if where == path]


class StubHandler(BaseHTTPRequestHandler):
    """Routes to the owning `Stub`; a chunked request body (a streamed one) is decoded."""

    stub: Stub

    def _body(self) -> bytes:
        match self.headers.get("transfer-encoding"):
            case "chunked":
                return b"".join(iter(self._chunk, b""))
            case _:
                return self.rfile.read(int(self.headers.get("content-length") or 0))

    def _chunk(self) -> bytes:
        size = int(self.rfile.readline().strip() or b"0", 16)
        data = self.rfile.read(size)
        self.rfile.readline()
        return data

    def _serve(self) -> None:
        body = self._body()
        self.stub.sent.append((self.command, self.path, {k.lower(): v for k, v in self.headers.items()}, body))
        status, payload = self.stub.routes.get((self.command, self.path), lambda _body: (404, b"{}"))(body)
        self.send_response(status)
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_GET = do_POST = _serve  # noqa: N815 — names imposed by http.server

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 — name imposed by http.server
        """Quiet."""


@pytest.fixture
def stub() -> Iterator[Stub]:
    """A live service on localhost, no routes yet: tests teach it what to answer."""
    served = Stub()
    handler = type("Handler", (StubHandler,), {"stub": served})
    with ThreadingHTTPServer(("127.0.0.1", 0), handler) as srv:
        served.url = f"http://127.0.0.1:{srv.server_port}"
        worker = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        worker.start()
        yield served
        srv.shutdown()
        worker.join()


##### HTTP #####
### a loopback port nothing listens on: a provider that is down, refused at once.
DOWN: Final[str] = "http://127.0.0.1:9"


@pytest.fixture
async def http() -> AsyncIterator[HttpPort]:
    """The process's HTTP driver, open, with no base: the drivers that ride it name absolute URLs."""
    async with HttpDriver() as driver:
        yield driver


##### QUEUE #####
@pytest.fixture
async def awa(queue_settings: QueueSettings) -> AsyncIterator[AwaDriver]:
    async with AwaDriver(queue_settings) as adapter:
        yield adapter


@pytest.fixture
async def refuse(queue_database: str) -> AsyncIterator[Callable[[], Awaitable[None]]]:
    """Make the queue's database refuse every new connection — those already open stay — as a server out of slots
    does; it accepts them again once the test is over."""
    name = queue_database.rpartition("/")[2]

    async def allow(flag: bool) -> None:
        ### ALTER DATABASE takes no parameters; the name is this worker's queue database.
        await admin(queue_database, (f'ALTER DATABASE "{name}" ALLOW_CONNECTIONS {str(flag).lower()}', []))

    try:
        yield partial(allow, False)
    finally:
        await allow(True)


async def reported(run: BackgroundRun) -> None:
    await run.report({"done": True})


@pytest.fixture
def handler() -> BackgroundHandler:
    """A job's handler that reports once and returns."""
    return reported


@pytest.fixture
def stuck(monkeypatch: pytest.MonkeyPatch) -> None:
    """An awa shutdown that never returns — after it has really stopped the runtime and closed the pool, so a test
    that lets the client go leaks no connection."""
    shutdown, close = AsyncClient.shutdown, AsyncClient.close

    async def never(client: AsyncClient, timeout_ms: int = 2000) -> None:
        await shutdown(client, timeout_ms)
        await close(client)
        await anyio.sleep_forever()

    monkeypatch.setattr(AsyncClient, "shutdown", never)


##### ENGINES — the same contract on awa and on PgQueuer, each on a database of its own #####
@pytest.fixture(params=["awa", "pgqueuer"])
def port(request: pytest.FixtureRequest, queue_settings: QueueSettings) -> AwaDriver | PgqueuerDriver:
    """The durable engine under test, not yet connected."""
    match request.param:
        case "awa":
            return AwaDriver(queue_settings)
        case _:
            dsn = Secret(request.getfixturevalue("pgqueuer_database"))
            return PgqueuerDriver(queue_settings.model_copy(update={"dsn": dsn}))


@pytest.fixture
def engine(queue_settings: QueueSettings, pgqueuer_database: str) -> PgqueuerDriver:
    """A PgQueuer engine on this worker's database, short timeouts, not yet connected."""
    update = {"dsn": Secret(pgqueuer_database), "timeout": timedelta(seconds=1), "drain": timedelta(seconds=1)}
    return PgqueuerDriver(queue_settings.model_copy(update=update))


@dataclass(slots=True)
class Flaky:
    """A handler that fails its first `fails` attempts, then reports and returns."""

    fails: int
    seen: int = 0

    async def __call__(self, run: BackgroundRun) -> None:
        self.seen += 1
        _ = self.seen <= self.fails and self._fail()
        await run.report({"attempt": self.seen})

    def _fail(self) -> None:
        msg = f"attempt {self.seen} failed"
        raise RuntimeError(msg)


@dataclass(slots=True)
class Hang:
    """A handler that reports, then waits forever; `cancelled` once its wait was interrupted."""

    cancelled: bool = False

    async def __call__(self, run: BackgroundRun) -> None:
        await run.report({"hanging": True})
        try:
            await anyio.sleep_forever()
        except anyio.get_cancelled_exc_class():
            self.cancelled = True
            raise


@pytest.fixture
def hang() -> Hang:
    return Hang()


@pytest.fixture
def flaky() -> Callable[[int], Flaky]:
    return Flaky


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
async def pg(pg_settings: PostgresSettings) -> AsyncIterator[PostgresDriver]:
    """A connected adapter over a fresh `adapters` schema holding one probe table, dropped after the test."""
    async with PostgresDriver(pg_settings) as adapter:
        await adapter.execute("CREATE EXTENSION IF NOT EXISTS vector")
        await adapter.execute("DROP SCHEMA IF EXISTS adapters CASCADE")
        await adapter.execute("CREATE SCHEMA adapters")
        await adapter.execute("CREATE TABLE adapters.probe (id int PRIMARY KEY, label text, v vector(3))")
        yield adapter
        await adapter.execute("DROP SCHEMA adapters CASCADE")
