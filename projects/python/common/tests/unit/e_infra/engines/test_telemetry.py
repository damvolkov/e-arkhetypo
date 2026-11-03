"""tests/unit/e_infra/engines/telemetry: the guarded facade — no provider, a real one in memory, one that fails."""

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from e_infra.engines.telemetry import FAILED, TelemetryEngine
from e_infra.infra.config.providers.drivers.telemetry.otel import OtelSettings
from e_infra.ports.telemetry import SpanRole, SpanStatus
from e_infra.providers.drivers.telemetry.otel import OtelDriver

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Generator

    from unit.e_infra.conftest import Logs


class Broken:
    """A provider whose every call raises: the facade must never let it reach the caller."""

    @contextmanager
    def span(self, *_args: Any, **_kwargs: Any) -> Generator[Any]:
        msg = "collector gone"
        raise RuntimeError(msg)
        yield

    def carrier(self) -> dict[str, str]:
        msg = "no context"
        raise RuntimeError(msg)

    @contextmanager
    def resume(self, _carrier: Any) -> Generator[None]:
        msg = "unreadable"
        raise RuntimeError(msg)
        yield


@pytest.fixture
def exporter() -> InMemorySpanExporter:
    return InMemorySpanExporter()


@pytest.fixture
async def traced(exporter: InMemorySpanExporter) -> AsyncIterator[TelemetryEngine]:
    async with OtelDriver(OtelSettings(), exporter) as otel:
        yield TelemetryEngine(otel)


##### NO PROVIDER — every call a no-op #####
async def test_telemetry_without_a_provider_runs_untraced() -> None:
    off = TelemetryEngine()
    with off.resume({"traceparent": "x"}), off.span("work", SpanRole.CALL):
        off.record({"a": 1})
        off.event("e", {"b": 2})
        off.status(SpanStatus.ERROR)
        assert off.carrier() == {}


##### A PROVIDER — the span current inside the block #####
async def test_telemetry_writes_land_on_the_current_span(
    traced: TelemetryEngine, exporter: InMemorySpanExporter
) -> None:
    with traced.span("work", SpanRole.JOB, {"job.id": "1"}):
        traced.record({"done": True})
        traced.event("progress", {"seen": 3, "where": ("a",), "none": None})
        traced.status(SpanStatus.ERROR, "said so")
    traced.record({"outside": 1})
    (span,) = exporter.get_finished_spans()
    assert (span.name, dict(span.attributes or {})) == (
        "work",
        {"openinference.span.kind": "CHAIN", "job.id": "1", "done": True},
    )
    assert dict(span.events[0].attributes or {}) == {"seen": 3, "where": "('a',)"}
    assert span.status.description == "said so"


async def test_telemetry_carries_a_trace_only_inside_a_span(
    traced: TelemetryEngine, exporter: InMemorySpanExporter
) -> None:
    assert traced.carrier() == {}
    with traced.span("submit", SpanRole.REQUEST):
        carrier = traced.carrier()
    with traced.resume(carrier), traced.span("job", SpanRole.JOB):
        pass
    with traced.resume({}), traced.span("alone", SpanRole.CALL):
        pass
    submit, job, alone = exporter.get_finished_spans()
    assert job.context.trace_id == submit.context.trace_id
    assert alone.context.trace_id != submit.context.trace_id


async def test_telemetry_a_raise_settles_the_span_and_propagates(
    traced: TelemetryEngine, exporter: InMemorySpanExporter
) -> None:
    def fail() -> None:
        with traced.span("work", SpanRole.CALL):
            msg = "boom"
            raise ValueError(msg)

    with pytest.raises(ValueError, match="boom"):
        fail()
    (span,) = exporter.get_finished_spans()
    assert span.status.is_ok is False


##### A FAILING PROVIDER — a warning, never the caller's failure #####
async def test_telemetry_a_failing_provider_costs_the_trace_not_the_call(logs: Logs) -> None:
    broken = TelemetryEngine(Broken())  # ty: ignore[invalid-argument-type]
    ran = False
    with broken.span("work", SpanRole.CALL), broken.resume({"traceparent": "x"}):
        ran = True
        assert broken.carrier() == {}
    assert ran
    assert logs.at("warning") == [FAILED, FAILED]


##### LOGS — a line inside a span is one of its events #####
async def test_telemetry_processor_turns_a_log_line_into_an_event_with_its_ids(
    traced: TelemetryEngine, exporter: InMemorySpanExporter
) -> None:
    outside = TelemetryEngine.processor(None, "info", {"event": "before"})
    with traced.span("work", SpanRole.CALL):
        inside = TelemetryEngine.processor(None, "info", {"event": "step", "n": 1, "none": None})
        failed = TelemetryEngine.processor(None, "warning", {"event": FAILED})
    (span,) = exporter.get_finished_spans()
    assert outside == {"event": "before"}
    assert failed == {"event": FAILED}
    assert (inside["trace_id"], inside["span_id"]) == (
        format(span.context.trace_id, "032x"),
        format(span.context.span_id, "016x"),
    )
    assert [(event.name, dict(event.attributes or {})) for event in span.events] == [("step", {"n": 1})]
