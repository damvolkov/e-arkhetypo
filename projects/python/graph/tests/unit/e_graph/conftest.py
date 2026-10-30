"""tests/unit/e_graph: the live app on the real state — env seeded before the lazy core singletons ever load.

`os.environ` stays untouched at module import (doctrine: no side-effect between imports); the seeding
rides `pytest_configure`, which pytest runs before collection. Collection matters: pytest probes every
test-module global for `__test__` (anyio's hook calls `getattr(obj, "__test__", False)`), so a test
module holding `settings as st` at module level touches the LazyProxy during collection — the earliest
point any settings access can happen, and the reason a session fixture is already too late."""

import os
import socket
import tempfile
import types
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

import fakeredis
import fakeredis.aioredis
import pytest
from litestar.testing import TestClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from e_graph.api.lifespan import db
from e_graph.instrument.contexts import InstrumentContexts
from e_graph.instrument.graph import InstrumentGraph
from e_graph.instrument.state import InfraState, InstrumentState, ProcessorsState, ProvidersState, RunState
from e_graph.instrument.telemetry import InstrumentTelemetry
from e_graph.logic.agent import AgnosticAgent
from e_graph.logic.orchestrator.core import OrchestratorCore
from e_graph.logic.state import LogicState
from e_graph.main import create_app
from infra.config.providers.drivers.telemetry.otel import OtelSettings
from infra.state import State
from processors.doc import DocProcessor
from providers.drivers.store import redis as redis_module
from providers.drivers.telemetry.otel import OtelDriver
from support.docling import GoldenPort

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Iterator

    from pytest_httpserver import HTTPServer

    from providers.adapters.pages.liteparse import LiteparseAdapter


def pytest_configure() -> None:
    """Seed SECRET, a private DB_PATH and a test queue database before any collection-time settings touch; external
    env wins."""
    ### the db lifespan provisions the queue database on the local ParadeDB: a test one, never the service's.
    os.environ.setdefault("QUEUE_DSN", "postgresql://postgres:postgres@127.0.0.1:45011/e_graph_test_background")
    os.environ.setdefault("CRYPTO__SECRET", "unit-test-secret-0123456789")
    os.environ.setdefault("DB_PATH", str(Path(tempfile.mkdtemp(prefix="e-graph-tests-")) / "test.db"))
    ### docling-serve is a local HTTP server in the test run, on a free port of its own — never the stack's.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        os.environ["DOCLING_URL"] = f"http://127.0.0.1:{probe.getsockname()[1]}"


class FakePsqlpyDriver:
    """The database driver of the db lifespan with no database behind it: every provision creates."""

    def __init__(self, _settings: object) -> None: ...

    async def provision(self) -> bool:
        return True


@pytest.fixture(scope="session")
def httpserver_listen_address() -> tuple[str, int]:
    """Where the plugin's session server listens: the port `pytest_configure` gave DOCLING_URL."""
    parts = urlsplit(os.environ["DOCLING_URL"])
    return parts.hostname or "127.0.0.1", parts.port or 0


@pytest.fixture
def docling(httpserver: HTTPServer) -> HTTPServer:
    """docling-serve answering its readiness route."""
    httpserver.expect_request("/ready").respond_with_data("ok")
    return httpserver


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, docling: HTTPServer) -> Iterator[TestClient]:
    """The live app with no service behind it: Postgres and Redis are fakes, docling a local HTTP server."""
    monkeypatch.setattr(db, "PsqlpyDriver", FakePsqlpyDriver)
    server = fakeredis.FakeServer()
    monkeypatch.setattr(redis_module.redis, "from_url", lambda _url, **_kw: fakeredis.aioredis.FakeRedis(server=server))
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def exporter() -> InMemorySpanExporter:
    """The spans the telemetry provider finished, readable in memory."""
    return InMemorySpanExporter()


@pytest.fixture
async def system(exporter: InMemorySpanExporter, pages: LiteparseAdapter) -> AsyncIterator[State]:
    """A sealed system graph shaped like the app's: `infra` with a live telemetry provider, `logic`, and `instrument`
    with an open contexts store.

    The providers and engines no instrument test touches stay absent; the agent is real but never called here;
    documents read through the golden conversions (`support.docling.GoldenPort`) and the real fast pass."""
    port = GoldenPort()
    async with OtelDriver(OtelSettings(), exporter) as telemetry, AgnosticAgent() as agent:
        infra = InfraState(
            providers=ProvidersState(store=None, telemetry=telemetry, redis=None, http=None, docling=port, pages=pages),  # ty: ignore[invalid-argument-type]
            engines=None,  # ty: ignore[invalid-argument-type]
            processors=ProcessorsState(doc=DocProcessor(port, pages)),
            graphs=MappingProxyType({"probe": InstrumentGraph(name="probe")}),
        )
        graph = State(
            infra=infra,
            logic=LogicState(agent=agent, orchestrator=OrchestratorCore()),
            instrument=InstrumentState(telemetry=InstrumentTelemetry(telemetry), contexts=InstrumentContexts()),
        )
        graph.seal()
        yield graph


@pytest.fixture
def run_state(system: State) -> RunState:
    return RunState(system)


@pytest.fixture
def located() -> Callable[..., Any]:
    """A clone of a test-local function, placed where the node contract demands: `pipelines/<pipeline>/nodes/<category>/node.py`.

    A clone, never the original: the module-level function stays where it was for every other test.
    Typed `Any` on purpose — the same helper feeds valid nodes to the graph and broken ones to the contract."""

    def place(func: types.FunctionType, category: str = "extract", pipeline: str = "doc") -> Any:
        clone = types.FunctionType(func.__code__, func.__globals__, func.__name__, func.__defaults__, func.__closure__)
        clone.__qualname__, clone.__doc__ = func.__qualname__, func.__doc__
        ### 3.14 annotations are lazy: the clone shares the original's annotate function, never evaluates it here.
        clone.__annotate__ = func.__annotate__  # ty: ignore[invalid-assignment] — typeshed types getter and setter apart
        clone.__module__ = f"e_graph.pipelines.{pipeline}.nodes.{category}.node"
        return clone

    return place
