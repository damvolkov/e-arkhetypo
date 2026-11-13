"""e_infra/providers/drivers/telemetry/otel: private provider, the span handle, every exporter road, sampling, settings."""

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter as GrpcExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter as HTTPExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind as SdkKind
from opentelemetry.trace import StatusCode
from pydantic import SecretStr

from e_infra.infra.config.providers import OTelProtocol
from e_infra.infra.errors import ProviderError, TelemetryError
from e_infra.ports.telemetry import SpanKey, SpanKind, SpanPort, SpanRole, SpanStatus, TelemetryPort
from e_infra.providers.drivers.telemetry.otel import (
    KINDS,
    ROLES,
    STATUSES,
    OTelDriver,
    OTelExporter,
    OTelSpan,
)
from unit.e_infra.conftest import otel_args

if TYPE_CHECKING:
    from unit.e_infra.conftest import Logs


@pytest.fixture
def exporter() -> InMemorySpanExporter:
    return InMemorySpanExporter()


##### CONTRACT #####
async def test_otel_satisfies_the_ports(exporter: InMemorySpanExporter) -> None:
    assert isinstance(OTelDriver(**otel_args()), TelemetryPort)
    async with OTelDriver(**otel_args(), exporter=exporter) as adapter:
        with adapter.span("work", {}) as span:
            assert isinstance(span, SpanPort)


def test_every_kind_and_status_maps_to_the_sdk() -> None:
    assert set(KINDS) == set(SpanKind)
    assert set(STATUSES) == set(SpanStatus)


##### SPAN #####
async def test_span_ids_are_w3c_hex(exporter: InMemorySpanExporter) -> None:
    async with OTelDriver(**otel_args(service="svc"), exporter=exporter) as adapter:
        with adapter.span("work", {"k": "v"}) as span:
            ids = (span.trace_id, span.span_id)
    assert (len(ids[0]), len(ids[1])) == (32, 16)
    (finished,) = exporter.get_finished_spans()
    assert (finished.name, finished.attributes, finished.kind) == ("work", {"k": "v"}, SdkKind.INTERNAL)
    assert finished.resource.attributes["service.name"] == "svc"


async def test_clean_exit_settles_ok(exporter: InMemorySpanExporter) -> None:
    async with OTelDriver(**otel_args(), exporter=exporter) as adapter:
        with adapter.span("fine", {}):
            pass
    (span,) = exporter.get_finished_spans()
    assert span.status.status_code is StatusCode.OK


async def test_handle_records_events_and_kind(exporter: InMemorySpanExporter) -> None:
    async with OTelDriver(**otel_args(), exporter=exporter) as adapter:
        with adapter.span("call", {"a": 1}, kind=SpanKind.CLIENT) as span:
            span.record({"output.value": "done"})
            span.event("checkpoint", {"step": 2})
    (finished,) = exporter.get_finished_spans()
    assert finished.attributes == {"a": 1, "output.value": "done"}
    assert finished.kind is SdkKind.CLIENT
    assert (finished.events[0].name, dict(finished.events[0].attributes or {})) == ("checkpoint", {"step": 2})


async def test_explicit_verdict_survives_a_clean_exit(exporter: InMemorySpanExporter) -> None:
    """A failure caught inside the block (a run's verdict) is written by hand and must not turn OK."""
    async with OTelDriver(**otel_args(), exporter=exporter) as adapter:
        with adapter.span("run", {}) as span:
            span.status(SpanStatus.ERROR, "RuntimeError: boom")
            assert isinstance(span, OTelSpan)
            assert span.settled
    (finished,) = exporter.get_finished_spans()
    assert (finished.status.status_code, finished.status.description) == (StatusCode.ERROR, "RuntimeError: boom")


async def test_error_recorded_then_propagated(exporter: InMemorySpanExporter) -> None:
    msg = "boom"
    async with OTelDriver(**otel_args(), exporter=exporter) as adapter:
        with pytest.raises(ValueError, match=msg), adapter.span("fails", {}):
            raise ValueError(msg)
    (span,) = exporter.get_finished_spans()
    assert span.status.status_code is StatusCode.ERROR
    assert span.events[0].name == "exception"


async def test_nested_spans_share_the_trace(exporter: InMemorySpanExporter) -> None:
    async with OTelDriver(**otel_args(), exporter=exporter) as adapter:
        with adapter.span("run", {}) as outer, adapter.span("node", {}) as inner:
            pass
    assert inner.trace_id == outer.trace_id
    child = next(span for span in exporter.get_finished_spans() if span.name == "node")
    assert child.parent is not None
    assert format(child.parent.span_id, "016x") == outer.span_id


##### EXPORT #####
def test_http_exporter_built_with_headers_and_deadline() -> None:
    exporter = OTelExporter.http("http://collector:4318", {"x-key": "k"}, 3.0)
    assert isinstance(exporter, HTTPExporter)
    exporter.shutdown()


@pytest.mark.parametrize("endpoint", ["http://collector:4317", "https://collector:4317"])
def test_grpc_exporter_built_for_plain_and_tls_collectors(endpoint: str) -> None:
    exporter = OTelExporter.grpc(endpoint, {"x-key": "k"}, 3.0)
    assert isinstance(exporter, GrpcExporter)
    exporter.shutdown()


@pytest.mark.parametrize("protocol", list(OTelProtocol))
async def test_processor_roads(protocol: OTelProtocol) -> None:
    assert OTelDriver(**otel_args())._enter_processor() is None
    assert isinstance(
        OTelDriver(**otel_args(), exporter=InMemorySpanExporter())._enter_processor(), SimpleSpanProcessor
    )
    settings = otel_args(
        endpoint="http://127.0.0.1:4318/",
        protocol=protocol,
        headers={"authorization": SecretStr("Bearer x")},
        flush=timedelta(milliseconds=200),
    )
    batched = OTelDriver(**settings)._enter_processor()
    assert isinstance(batched, BatchSpanProcessor)
    batched.shutdown()


async def test_endpoint_road_connects_and_closes() -> None:
    """A collector that never answers: no span is opened, so shutdown has nothing to flush."""
    async with OTelDriver(**otel_args(endpoint="http://127.0.0.1:9")) as adapter:
        assert adapter.spec.name == "otel"


async def test_zero_sample_keeps_nothing(exporter: InMemorySpanExporter) -> None:
    async with OTelDriver(**otel_args(sample=0.0), exporter=exporter) as adapter:
        with adapter.span("dropped", {}) as span:
            assert len(span.trace_id) == 32
    assert exporter.get_finished_spans() == ()


async def test_closed_driver_refuses_spans() -> None:
    adapter = OTelDriver(**otel_args())
    async with adapter:
        pass
    await adapter.__aexit__(None, None, None)
    with pytest.raises(TelemetryError, match="not open"), adapter.span("late", {}):
        pass


##### RESOURCE #####
async def test_resource_carries_the_configured_attributes(exporter: InMemorySpanExporter) -> None:
    settings = otel_args(service="svc", attributes={"openinference.project.name": "proj", "service.name": "x"})
    async with OTelDriver(**settings, exporter=exporter) as adapter:
        with adapter.span("work", {}):
            pass
    (span,) = exporter.get_finished_spans()
    assert span.resource.attributes["openinference.project.name"] == "proj"
    assert span.resource.attributes["service.name"] == "svc"


##### HEALTH #####
async def test_otel_health(exporter: InMemorySpanExporter, monkeypatch: pytest.MonkeyPatch) -> None:
    """The provider flushes to its exporter; one that cannot flush, or no provider, is down."""
    adapter = OTelDriver(**otel_args(), exporter=exporter)
    with pytest.raises(ProviderError):
        await adapter.health()
    async with adapter:
        assert await adapter.health()
        monkeypatch.setattr(TracerProvider, "force_flush", lambda *_: False)
        with pytest.raises(ProviderError):
            await adapter.health()


async def test_otel_lifecycle_and_an_unhealthy_provider_are_logged(
    exporter: InMemorySpanExporter, monkeypatch: pytest.MonkeyPatch, logs: Logs
) -> None:
    adapter = OTelDriver(**otel_args(service="svc"), exporter=exporter)
    with pytest.raises(ProviderError):
        await adapter.health()
    async with adapter:
        monkeypatch.setattr(TracerProvider, "force_flush", lambda *_: False)
        with pytest.raises(ProviderError):
            await adapter.health()
        with adapter.span("work", {}):
            pass
    assert logs.at("info") == ["otel opened", "otel closed"]
    assert logs.at("warning") == ["otel unhealthy", "otel unhealthy"]
    assert logs.at("debug") == ["otel span"]


##### ROLES — the service's vocabulary in OTel's and OpenInference's words #####
def test_every_role_has_a_kind_and_a_convention() -> None:
    assert set(ROLES) == set(SpanRole)


@pytest.mark.parametrize(
    ("role", "kind", "convention", "model"),
    [
        (SpanRole.LLM, SdkKind.CLIENT, "LLM", "llm.model_name"),
        (SpanRole.EMBEDDING, SdkKind.CLIENT, "EMBEDDING", "embedding.model_name"),
        (SpanRole.JOB, SdkKind.CONSUMER, "CHAIN", "llm.model_name"),
    ],
    ids=["llm", "embedding", "job"],
)
async def test_a_role_picks_the_kind_the_convention_and_its_own_key_names(
    exporter: InMemorySpanExporter, role: SpanRole, kind: SdkKind, convention: str, model: str
) -> None:
    async with OTelDriver(**otel_args(), exporter=exporter) as adapter:
        with adapter.span("call", {SpanKey.MODEL: "m", "free.key": 1}, SpanKind.INTERNAL, role=role) as span:
            span.record({SpanKey.OUTPUT: "done"})
            span.event("step", {SpanKey.SIZE: 3})
    (finished,) = exporter.get_finished_spans()
    assert finished.kind == kind
    assert dict(finished.attributes or {}) == {
        "openinference.span.kind": convention,
        model: "m",
        "free.key": 1,
        "output.value": "done",
    }
    assert dict(finished.events[0].attributes or {}) == {"input.size": 3}


async def test_without_a_role_the_span_is_as_written(exporter: InMemorySpanExporter) -> None:
    async with OTelDriver(**otel_args(), exporter=exporter) as adapter:
        with adapter.span("raw", {SpanKey.MODEL: "m"}, SpanKind.SERVER):
            pass
    (finished,) = exporter.get_finished_spans()
    assert (finished.kind, dict(finished.attributes or {})) == (SdkKind.SERVER, {"model": "m"})


##### CARRIER — a trace across a queue #####
async def test_a_carrier_resumed_makes_the_child_of_its_trace(exporter: InMemorySpanExporter) -> None:
    async with OTelDriver(**otel_args(), exporter=exporter) as adapter:
        assert adapter.carrier() == {}
        with adapter.span("submit", {}) as parent:
            carrier = adapter.carrier()
        with adapter.resume(carrier), adapter.span("job", {}) as child:
            pass
        assert adapter.carrier() == {}
    assert "traceparent" in carrier
    assert child.trace_id == parent.trace_id
    job = next(span for span in exporter.get_finished_spans() if span.name == "job")
    assert job.parent is not None
    assert format(job.parent.span_id, "016x") == parent.span_id


async def test_the_tracer_is_named_by_the_service(exporter: InMemorySpanExporter) -> None:
    async with OTelDriver(**otel_args(service="svc"), exporter=exporter) as adapter:
        with adapter.span("work", {}):
            pass
    (finished,) = exporter.get_finished_spans()
    assert finished.instrumentation_scope is not None
    assert finished.instrumentation_scope.name == "svc"
