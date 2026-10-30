"""providers/drivers/telemetry/otel: TelemetryPort over the official OpenTelemetry SDK, exported by OTLP over HTTP or gRPC.

A singleton like every provider: one per process, opened by the lifespan, closed by it. It owns its own
`TracerProvider` — never the process-global one: two apps, two tests, two providers, zero cross-talk.
The exporter resolves once: an injected `SpanExporter` wins (tests read spans in memory), then
`OTEL_ENDPOINT` batches to a collector over `OTEL_PROTOCOL`, and with neither the spans are still minted
— their ids correlate logs and outputs, they just leave no process. Sampling is parent-based at
`OTEL_SAMPLE`. Each `span` yields an `OtelSpan` (the `SpanPort`): attributes, events and status may be
written until the block ends; a clean exit settles OK, a raise settles ERROR with the exception recorded.
Spans nest through the SDK's contextvars, so a span opened inside another is its child across awaits."""

import asyncio
from contextlib import contextmanager
from types import MappingProxyType
from typing import TYPE_CHECKING, ClassVar, Final, Self

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter as GrpcExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter as HttpExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter, SpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
from opentelemetry.trace import Status, StatusCode

from e_infra.infra.config.providers.drivers.telemetry.otel import OtelProtocol
from e_infra.infra.errors import TelemetryError
from e_infra.infra.logger import logger
from e_infra.infra.settings import settings as st
from e_infra.ports.provider import Isolation, Locality, ProviderSpec, Workload
from e_infra.ports.telemetry import SpanKind, SpanStatus

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Mapping

    from opentelemetry.trace import Tracer

    from e_infra.infra.config.providers.drivers.telemetry.otel import OtelSettings
    from e_infra.ports.telemetry import AttributeValue

TRACES_PATH: Final[str] = "/v1/traces"
MS_PER_SECOND: Final[float] = 1000.0
KINDS: Final[Mapping[SpanKind, trace.SpanKind]] = MappingProxyType(
    {
        SpanKind.INTERNAL: trace.SpanKind.INTERNAL,
        SpanKind.SERVER: trace.SpanKind.SERVER,
        SpanKind.CLIENT: trace.SpanKind.CLIENT,
        SpanKind.PRODUCER: trace.SpanKind.PRODUCER,
        SpanKind.CONSUMER: trace.SpanKind.CONSUMER,
    }
)
STATUSES: Final[Mapping[SpanStatus, StatusCode]] = MappingProxyType(
    {
        SpanStatus.UNSET: StatusCode.UNSET,
        SpanStatus.OK: StatusCode.OK,
        SpanStatus.ERROR: StatusCode.ERROR,
    }
)


##### EXPORTERS — one handler per transport, chosen by value #####
def export_http(endpoint: str, headers: dict[str, str], timeout: float) -> SpanExporter:
    """OTLP over HTTP/protobuf: the collector's base URL, traces under `/v1/traces`."""
    return HttpExporter(endpoint=f"{endpoint}{TRACES_PATH}", headers=headers, timeout=timeout)


def export_grpc(endpoint: str, headers: dict[str, str], timeout: float) -> SpanExporter:
    """OTLP over gRPC: a plain `http://` collector is a local, unencrypted one; anything else negotiates TLS."""
    return GrpcExporter(endpoint=endpoint, insecure=endpoint.startswith("http://"), headers=headers, timeout=timeout)


EXPORTERS: Final[Mapping[OtelProtocol, Callable[[str, dict[str, str], float], SpanExporter]]] = MappingProxyType(
    {
        OtelProtocol.HTTP: export_http,
        OtelProtocol.GRPC: export_grpc,
    }
)


##### SPAN #####
class OtelSpan:
    """The `SpanPort` over one live SDK span: ids in W3C hex, writes forwarded until the span ends."""

    __slots__ = ("_settled", "_span")

    def __init__(self, span: trace.Span) -> None:
        self._span = span
        self._settled = False

    ############################################################

    @property
    def trace_id(self) -> str:
        return format(self._span.get_span_context().trace_id, "032x")

    @property
    def span_id(self) -> str:
        return format(self._span.get_span_context().span_id, "016x")

    @property
    def settled(self) -> bool:
        """Whether a verdict was written explicitly — then the clean exit leaves it alone."""
        return self._settled

    def record(self, attributes: Mapping[str, AttributeValue]) -> None:
        self._span.set_attributes(attributes)

    def event(self, name: str, attributes: Mapping[str, AttributeValue]) -> None:
        self._span.add_event(name, attributes)

    def status(self, status: SpanStatus, description: str = "") -> None:
        ### OTel accepts a description on ERROR only: anything else would be dropped with a warning.
        self._span.set_status(Status(STATUSES[status], description if status is SpanStatus.ERROR else None))
        self._settled = True


##### DRIVER #####
class OtelDriver:
    """Spans on a private provider: open with `span`, write through the yielded `OtelSpan`, flushed on close."""

    spec: ClassVar[ProviderSpec] = ProviderSpec("otel", Locality.REMOTE, Workload.IO_BOUND, Isolation.LOOP)

    def __init__(self, settings: OtelSettings | None = None, exporter: SpanExporter | None = None) -> None:
        ### the default is read on call, not at import: the settings singleton stays lazy.
        self._settings = st.providers.drivers.telemetry.otel if settings is None else settings
        self._exporter = exporter
        self._provider: TracerProvider | None = None
        self._tracer: Tracer | None = None

    ##### PRIVATE METHODS #####

    def _enter_exporter(self) -> SpanExporter:
        """The OTLP exporter for the configured transport, headers and deadline."""
        resolved = self._settings
        headers = {key: secret.get_secret_value() for key, secret in resolved.headers.items()}
        exporter = EXPORTERS[resolved.protocol]
        return exporter(resolved.endpoint.rstrip("/"), headers, resolved.timeout.total_seconds())

    def _enter_processor(self) -> SpanProcessor | None:
        match (self._exporter, self._settings.endpoint):
            case (None, ""):
                return None
            case (None, _):
                return BatchSpanProcessor(
                    self._enter_exporter(),
                    schedule_delay_millis=self._settings.flush.total_seconds() * MS_PER_SECOND,
                    export_timeout_millis=self._settings.timeout.total_seconds() * MS_PER_SECOND,
                )
            case (SpanExporter() as exporter, _):
                return SimpleSpanProcessor(exporter)

    def _common_open(self) -> Tracer:
        match self._tracer:
            case None:
                msg = "OtelDriver is not open: the lifespan opens it, handlers never do"
                raise TelemetryError(msg)
            case tracer:
                return tracer

    ############################################################

    ##### PUBLIC #####

    async def __aenter__(self) -> Self:
        resolved = self._settings
        ### the service name is the settings' own field: an attribute of the same key never overrides it.
        resource = Resource.create({**resolved.attributes, "service.name": resolved.service})
        provider = TracerProvider(resource=resource, sampler=ParentBased(TraceIdRatioBased(resolved.sample)))
        match self._enter_processor():
            case None:
                pass
            case processor:
                provider.add_span_processor(processor)
        self._provider = provider
        self._tracer = provider.get_tracer("e-stack")
        logger.info("otel opened", service=resolved.service, endpoint=resolved.endpoint, sample=resolved.sample)
        return self

    async def __aexit__(self, *exc: object) -> None:
        match self._provider:
            case None:
                return
            case provider:
                self._tracer = None
                self._provider = None
                ### shutdown flushes the batch over the network: blocking I/O, so it leaves the loop.
                await asyncio.to_thread(provider.shutdown)
                logger.info("otel closed")

    async def health(self) -> bool:
        """The provider is open and flushes what it holds to its exporter within OTEL_TIMEOUT (none set: nothing to
        flush, it answers at once)."""
        timeout = int(self._settings.timeout.total_seconds() * MS_PER_SECOND)
        match self._provider:
            case None:
                logger.warning("otel unhealthy", reason="not open")
                return False
            case provider:
                flushed = await asyncio.to_thread(provider.force_flush, timeout)
                _ = flushed or logger.warning("otel unhealthy", reason="flush timed out")
                return flushed

    @contextmanager
    def span(
        self, name: str, attributes: Mapping[str, AttributeValue], kind: SpanKind = SpanKind.INTERNAL
    ) -> Generator[OtelSpan]:
        """A current span around the block: a raise is recorded and settles ERROR, a clean exit settles OK."""
        tracer = self._common_open()
        logger.debug("otel span", name=name, kind=str(kind))
        with tracer.start_as_current_span(name, kind=KINDS[kind], attributes=attributes) as raw:
            span = OtelSpan(raw)
            yield span
            ### only reached on a clean exit: a verdict written explicitly (say, a failed run caught inside) stands.
            match span.settled:
                case True:
                    pass
                case _:
                    span.status(SpanStatus.OK)
