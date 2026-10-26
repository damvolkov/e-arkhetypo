"""tests/unit/e_infra/adapters/otel: private provider, the span handle, every exporter road, sampling, settings."""

from datetime import timedelta

import pytest
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter as GrpcExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter as HttpExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind as SdkKind
from opentelemetry.trace import StatusCode

from e_infra.adapters.base import PingError
from e_infra.adapters.otel import KINDS, STATUSES, OtelAdapter, OtelSpan, export_grpc, export_http
from e_infra.adapters.ports import SpanKind, SpanPort, SpanStatus, TelemetryPort
from e_infra.infra.settings.base import Secret
from e_infra.infra.settings.otel import OtelProtocol, OtelSettings


@pytest.fixture
def exporter() -> InMemorySpanExporter:
    return InMemorySpanExporter()


##### CONTRACT #####
async def test_otel_satisfies_the_ports(exporter: InMemorySpanExporter) -> None:
    assert isinstance(OtelAdapter(OtelSettings()), TelemetryPort)
    async with OtelAdapter(OtelSettings(), exporter) as adapter:
        with adapter.span("work", {}) as span:
            assert isinstance(span, SpanPort)


def test_every_kind_and_status_maps_to_the_sdk() -> None:
    assert set(KINDS) == set(SpanKind)
    assert set(STATUSES) == set(SpanStatus)


##### SPAN #####
async def test_span_ids_are_w3c_hex(exporter: InMemorySpanExporter) -> None:
    async with OtelAdapter(OtelSettings(otel_service="svc"), exporter) as adapter:
        with adapter.span("work", {"k": "v"}) as span:
            ids = (span.trace_id, span.span_id)
    assert (len(ids[0]), len(ids[1])) == (32, 16)
    (finished,) = exporter.get_finished_spans()
    assert (finished.name, finished.attributes, finished.kind) == ("work", {"k": "v"}, SdkKind.INTERNAL)
    assert finished.resource.attributes["service.name"] == "svc"


async def test_clean_exit_settles_ok(exporter: InMemorySpanExporter) -> None:
    async with OtelAdapter(OtelSettings(), exporter) as adapter:
        with adapter.span("fine", {}):
            pass
    (span,) = exporter.get_finished_spans()
    assert span.status.status_code is StatusCode.OK


async def test_handle_records_events_and_kind(exporter: InMemorySpanExporter) -> None:
    async with OtelAdapter(OtelSettings(), exporter) as adapter:
        with adapter.span("call", {"a": 1}, kind=SpanKind.CLIENT) as span:
            span.record({"output.value": "done"})
            span.event("checkpoint", {"step": 2})
    (finished,) = exporter.get_finished_spans()
    assert finished.attributes == {"a": 1, "output.value": "done"}
    assert finished.kind is SdkKind.CLIENT
    assert (finished.events[0].name, dict(finished.events[0].attributes or {})) == ("checkpoint", {"step": 2})


async def test_explicit_verdict_survives_a_clean_exit(exporter: InMemorySpanExporter) -> None:
    """A failure caught inside the block (a run's verdict) is written by hand and must not turn OK."""
    async with OtelAdapter(OtelSettings(), exporter) as adapter:
        with adapter.span("run", {}) as span:
            span.status(SpanStatus.ERROR, "RuntimeError: boom")
            assert isinstance(span, OtelSpan)
            assert span.settled
    (finished,) = exporter.get_finished_spans()
    assert (finished.status.status_code, finished.status.description) == (StatusCode.ERROR, "RuntimeError: boom")


async def test_error_recorded_then_propagated(exporter: InMemorySpanExporter) -> None:
    msg = "boom"
    async with OtelAdapter(OtelSettings(), exporter) as adapter:
        with pytest.raises(ValueError, match=msg), adapter.span("fails", {}):
            raise ValueError(msg)
    (span,) = exporter.get_finished_spans()
    assert span.status.status_code is StatusCode.ERROR
    assert span.events[0].name == "exception"


async def test_nested_spans_share_the_trace(exporter: InMemorySpanExporter) -> None:
    async with OtelAdapter(OtelSettings(), exporter) as adapter:
        with adapter.span("run", {}) as outer, adapter.span("node", {}) as inner:
            pass
    assert inner.trace_id == outer.trace_id
    child = next(span for span in exporter.get_finished_spans() if span.name == "node")
    assert child.parent is not None
    assert format(child.parent.span_id, "016x") == outer.span_id


##### EXPORT #####
def test_http_exporter_built_with_headers_and_deadline() -> None:
    exporter = export_http("http://collector:4318", {"x-key": "k"}, 3.0)
    assert isinstance(exporter, HttpExporter)
    exporter.shutdown()


@pytest.mark.parametrize("endpoint", ["http://collector:4317", "https://collector:4317"])
def test_grpc_exporter_built_for_plain_and_tls_collectors(endpoint: str) -> None:
    exporter = export_grpc(endpoint, {"x-key": "k"}, 3.0)
    assert isinstance(exporter, GrpcExporter)
    exporter.shutdown()


@pytest.mark.parametrize("protocol", list(OtelProtocol))
async def test_processor_roads(protocol: OtelProtocol) -> None:
    assert OtelAdapter(OtelSettings())._connect_processor() is None
    assert isinstance(OtelAdapter(OtelSettings(), InMemorySpanExporter())._connect_processor(), SimpleSpanProcessor)
    settings = OtelSettings(
        otel_endpoint="http://127.0.0.1:4318/",
        otel_protocol=protocol,
        otel_headers={"authorization": Secret("Bearer x")},
        otel_flush=timedelta(milliseconds=200),
    )
    batched = OtelAdapter(settings)._connect_processor()
    assert isinstance(batched, BatchSpanProcessor)
    batched.shutdown()


async def test_endpoint_road_connects_and_closes() -> None:
    """A collector that never answers: no span is opened, so shutdown has nothing to flush."""
    async with OtelAdapter(OtelSettings(otel_endpoint="http://127.0.0.1:9")) as adapter:
        assert adapter.name == "otel"


async def test_zero_sample_keeps_nothing(exporter: InMemorySpanExporter) -> None:
    async with OtelAdapter(OtelSettings(otel_sample=0.0), exporter) as adapter:
        with adapter.span("dropped", {}) as span:
            assert len(span.trace_id) == 32
    assert exporter.get_finished_spans() == ()


async def test_closed_adapter_refuses_spans() -> None:
    adapter = OtelAdapter(OtelSettings())
    async with adapter:
        pass
    await adapter.close()
    with pytest.raises(RuntimeError, match="not connected"), adapter.span("late", {}):
        pass


##### RESOURCE #####
async def test_resource_carries_the_configured_attributes(exporter: InMemorySpanExporter) -> None:
    settings = OtelSettings(
        otel_service="svc", otel_attributes={"openinference.project.name": "proj", "service.name": "x"}
    )
    async with OtelAdapter(settings, exporter) as adapter:
        with adapter.span("work", {}):
            pass
    (span,) = exporter.get_finished_spans()
    assert span.resource.attributes["openinference.project.name"] == "proj"
    assert span.resource.attributes["service.name"] == "svc"


def test_settings_read_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTEL_ATTRIBUTES", '{"openinference.project.name": "e-graph"}')
    monkeypatch.setenv("OTEL_PROTOCOL", "grpc")
    monkeypatch.setenv("OTEL_HEADERS", '{"api_key": "s3cret"}')
    monkeypatch.setenv("OTEL_FLUSH", "PT1S")
    settings = OtelSettings()
    assert settings.otel_attributes == {"openinference.project.name": "e-graph"}
    assert settings.otel_protocol is OtelProtocol.GRPC
    assert settings.otel_headers["api_key"].get_secret_value() == "s3cret"
    assert "s3cret" not in repr(settings)
    assert settings.otel_flush == timedelta(seconds=1)


@pytest.mark.parametrize("sample", [-0.1, 1.5])
def test_sample_is_a_share(sample: float) -> None:
    with pytest.raises(ValueError, match="sample"):
        OtelSettings(otel_sample=sample)


##### PING #####
async def test_otel_ping(exporter: InMemorySpanExporter, monkeypatch: pytest.MonkeyPatch) -> None:
    """The provider flushes to its exporter; one that cannot flush, or no provider, is down."""
    adapter = OtelAdapter(OtelSettings(), exporter)
    with pytest.raises(PingError, match=r"^otel: not connected$"):
        await adapter.ping()
    async with adapter:
        await adapter.ping()
        monkeypatch.setattr(TracerProvider, "force_flush", lambda *_: False)
        with pytest.raises(PingError, match=r"^otel: spans not flushed to the exporter$"):
            await adapter.ping()
