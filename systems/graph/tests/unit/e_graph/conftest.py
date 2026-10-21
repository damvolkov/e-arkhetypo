"""tests/unit/e_graph: the live app on the real state — env seeded before the lazy core singletons ever load.

`os.environ` stays untouched at module import (doctrine: no side-effect between imports); the seeding
rides `pytest_configure`, which pytest runs before collection. Collection matters: pytest probes every
test-module global for `__test__` (anyio's hook calls `getattr(obj, "__test__", False)`), so a test
module holding `settings as st` at module level touches the LazyProxy during collection — the earliest
point any settings access can happen, and the reason a session fixture is already too late."""

import os
import tempfile
import types
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

import pytest
from litestar.testing import TestClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from adapters.otel import OtelAdapter
from core.settings.otel import OtelSettings
from core.state import State
from e_graph.instrument.graph import InstrumentGraph
from e_graph.instrument.state import AdaptersState, ContextState, InfraState, ProcessorsState, RunState
from e_graph.instrument.telemetry import InstrumentTelemetry
from e_graph.logic.agent import AgnosticAgent
from e_graph.logic.orchestrator.core import OrchestratorCore
from e_graph.main import create_app
from processors.doc import DocProcessor
from support.docling import GoldenPort

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Iterator


def pytest_configure() -> None:
    """Seed SECRET, a private DB_PATH and a test queue database before any collection-time settings touch; external
    env wins."""
    ### the db lifespan provisions the queue database on the local ParadeDB: a test one, never the service's.
    os.environ.setdefault("QUEUE_DSN", "postgresql://postgres:postgres@127.0.0.1:45011/e_graph_test_background")
    os.environ.setdefault("CRYPTO__SECRET", "unit-test-secret-0123456789")
    os.environ.setdefault("DB_PATH", str(Path(tempfile.mkdtemp(prefix="e-graph-tests-")) / "test.db"))


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def exporter() -> InMemorySpanExporter:
    """The spans the telemetry edge finished, readable in memory."""
    return InMemorySpanExporter()


@pytest.fixture
async def system(exporter: InMemorySpanExporter) -> AsyncIterator[State]:
    """A sealed system graph shaped like the app's: `infra` with a live telemetry edge, an open contexts store.

    The edges no instrument test touches stay absent; the agent is real but never called here; documents
    read through the golden conversions (`support.docling.GoldenPort`)."""
    port = GoldenPort()
    async with OtelAdapter(OtelSettings(), exporter) as telemetry, AgnosticAgent() as agent:
        infra = InfraState(
            adapters=AdaptersState(store=None, telemetry=telemetry, redis=None, http=None, docling=port),  # ty: ignore[invalid-argument-type]
            processors=ProcessorsState(doc=DocProcessor(port)),
            agent=agent,
            orchestrator=OrchestratorCore(),
            telemetry=InstrumentTelemetry(telemetry),
            graphs=MappingProxyType({"probe": InstrumentGraph(name="probe")}),
        )
        graph = State(infra=infra, contexts=ContextState())
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
