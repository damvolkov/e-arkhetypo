"""tests/unit: instrument.telemetry — providers plug in by shape, the facade decides what a trace says."""

import json
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

import pytest

from adapters.otel import OtelAdapter
from adapters.ports import SpanKind, SpanPort, SpanStatus
from e_graph.instrument.contexts import InstrumentContexts
from e_graph.instrument.graph import InstrumentGraph
from e_graph.instrument.models import NodeOutput, NodeStatus, RunEnd, RunStatus
from e_graph.instrument.node import InstrumentNode
from e_graph.instrument.state import InfraState, InstrumentState, RunState
from e_graph.instrument.telemetry import NO_SPAN, InstrumentTelemetry, NullSpan, NullTelemetry, SpanTelemetry
from e_graph.logic.models import Usage
from e_graph.logic.state import LogicState
from infra.config.otel import OtelSettings
from infra.state import State

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping


class RecordingSpan:
    """A span of nobody's making: keeps every write so the test can read what the facade said."""

    def __init__(self) -> None:
        self.records: dict[str, Any] = {}
        self.verdict: tuple[SpanStatus, str] | None = None

    @property
    def trace_id(self) -> str:
        return "t" * 32

    @property
    def span_id(self) -> str:
        return "s" * 16

    def record(self, attributes: Mapping[str, Any]) -> None:
        self.records |= attributes

    def event(self, name: str, attributes: Mapping[str, Any]) -> None:
        self.records[f"event:{name}"] = dict(attributes)

    def status(self, status: SpanStatus, description: str = "") -> None:
        self.verdict = (status, description)


class RecordingTelemetry:
    """A provider of nobody's making: lines up by shape, remembers what it opened and the span it handed out."""

    def __init__(self) -> None:
        self.opened: list[tuple[str, dict[str, Any], SpanKind]] = []
        self.spans: list[RecordingSpan] = []

    @contextmanager
    def span(self, name: str, attributes: Mapping[str, Any], kind: SpanKind = SpanKind.INTERNAL) -> Iterator[SpanPort]:
        self.opened.append((name, dict(attributes), kind))
        self.spans.append(span := RecordingSpan())
        yield span


async def node_quiet(state: RunState) -> None:
    """Runs untraced."""


def test_providers_and_spans_line_up_by_shape() -> None:
    assert isinstance(OtelAdapter(OtelSettings()), SpanTelemetry)
    assert isinstance(NullTelemetry(), SpanTelemetry)
    assert isinstance(RecordingTelemetry(), SpanTelemetry)
    assert isinstance(NO_SPAN, SpanPort)
    assert isinstance(RecordingSpan(), SpanPort)


def test_no_provider_means_spans_that_keep_nothing() -> None:
    telemetry = InstrumentTelemetry()
    assert isinstance(telemetry.provider, NullTelemetry)
    with telemetry.run("r", {}) as run, telemetry.node("n", "extract", "mid", "r") as node:
        assert run is node is NO_SPAN
        assert isinstance(node, NullSpan)
        assert (node.trace_id, node.span_id) == ("", "")
        node.record({"k": "v"})
        node.event("e", {})
        node.status(SpanStatus.ERROR, "ignored")


def test_run_opens_with_its_input() -> None:
    provider = RecordingTelemetry()
    with InstrumentTelemetry(provider).run("r1", {"b": 2, "a": b"x", "odd": object}):
        pass
    name, attributes, kind = provider.opened[0]
    assert (name, kind, attributes["run.id"], attributes["openinference.span.kind"]) == (
        "run",
        SpanKind.INTERNAL,
        "r1",
        "CHAIN",
    )
    assert list(json.loads(attributes["input.value"])) == ["a", "b", "odd"]
    assert json.loads(attributes["input.value"])["odd"] == repr(object)
    assert attributes["input.mime_type"] == "application/json"


def test_node_opens_tagged_and_closes_with_its_summary() -> None:
    provider = RecordingTelemetry()
    telemetry = InstrumentTelemetry(provider)
    with telemetry.node("extract", "extract", "start", "r1") as span:
        telemetry.outcome(span, NodeOutput(summary="amount 3.50"))
    name, attributes, _ = provider.opened[0]
    assert name == "node.extract"
    assert attributes == {
        "openinference.span.kind": "CHAIN",
        "node.name": "extract",
        "node.category": "extract",
        "node.role": "start",
        "run.id": "r1",
    }
    assert provider.spans[0].records == {"node.summary": "amount 3.50", "output.value": "amount 3.50"}


def test_node_outcome_records_usage_and_extras() -> None:
    provider = RecordingTelemetry()
    telemetry = InstrumentTelemetry(provider)
    output = NodeOutput(
        summary="s", usage=Usage(input_tokens=3, output_tokens=2, total_tokens=5, calls=1), extra={"k": 1}
    )
    with telemetry.node("n", "extract", "mid", "r1") as span:
        telemetry.outcome(span, output)
    records = provider.spans[0].records
    assert (
        records["llm.token_count.prompt"],
        records["llm.token_count.completion"],
        records["llm.token_count.total"],
        records["node.agent.calls"],
    ) == (3, 2, 5, 1)
    assert json.loads(records["node.extra"]) == {"k": 1}


@pytest.mark.parametrize(
    ("status", "error", "verdict"),
    [(RunStatus.SUCCEEDED, "", SpanStatus.OK), (RunStatus.FAILED, "RuntimeError: x", SpanStatus.ERROR)],
)
def test_run_closes_with_its_verdict(status: RunStatus, error: str, verdict: SpanStatus) -> None:
    provider = RecordingTelemetry()
    telemetry = InstrumentTelemetry(provider)
    end = RunEnd(run_id="r1", status=status, latency_ms=4.5, skipped=("report",), error=error)
    with telemetry.run("r1", {}) as span:
        telemetry.verdict(span, end, {"amount": "1", "blob": b"x", "doc": State(pages=3)})
    recorded = provider.spans[0]
    assert json.loads(recorded.records["run.context"]) == {"amount": "1", "blob": "eA==", "doc": {"pages": 3}}
    assert (recorded.records["run.status"], recorded.records["run.latency_ms"]) == (status, 4.5)
    assert json.loads(recorded.records["output.value"])["skipped"] == ["report"]
    assert recorded.verdict == (verdict, error)


async def test_a_node_runs_untraced_without_a_provider(located: Callable[..., Any]) -> None:
    ### nothing but the instrument's tracer: a node needs no adapter to be traced, or not traced.
    ### no edge, no processor, no agent, no orchestrator: only the tracer is real.
    absent: Any = None
    infra = InfraState(
        adapters=absent,
        processors=absent,
        graphs={},
    )
    system = State(
        infra=infra,
        logic=LogicState(agent=absent, orchestrator=absent),
        instrument=InstrumentState(telemetry=InstrumentTelemetry(), contexts=InstrumentContexts()),
    )
    system.seal()
    node = InstrumentGraph().add_node(located(node_quiet)).nodes["quiet"]
    assert isinstance(node, InstrumentNode)
    output = await node.run(RunState(system))
    assert (output.status, output.trace_id, output.span_id, output.summary) == (
        NodeStatus.SUCCEEDED,
        "",
        "",
        "Runs untraced.",
    )
