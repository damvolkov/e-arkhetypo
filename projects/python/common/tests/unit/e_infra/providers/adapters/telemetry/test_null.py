"""tests/unit/e_infra/providers/adapters/telemetry/null: tracing off — the port met, nothing kept."""

from e_infra.ports.telemetry import SpanPort, SpanRole, SpanStatus, TelemetryPort
from e_infra.providers.adapters.telemetry.null import NullAdapter


async def test_null_meets_the_port_and_keeps_nothing() -> None:
    async with NullAdapter() as null:
        assert (isinstance(null, TelemetryPort), await null.health(), null.carrier()) == (True, True, {})
        with null.resume({"traceparent": "x"}), null.span("work", {"k": 1}, role=SpanRole.JOB) as span:
            span.record({"a": 1})
            span.event("e", {})
            span.status(SpanStatus.ERROR, "said")
            assert (isinstance(span, SpanPort), span.trace_id, span.span_id) == (True, "", "")
