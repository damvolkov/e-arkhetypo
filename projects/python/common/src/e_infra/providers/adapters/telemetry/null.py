"""providers/adapters/telemetry/null: the provider of no provider — tracing off.

Every span is opened and dropped: no ids, no export, nothing kept; the service runs exactly as traced, minus the traces.
The composition root plugs it where TELEMETRY_BACKEND says none, so nothing above the port branches on tracing."""

from contextlib import contextmanager
from typing import TYPE_CHECKING, ClassVar, Self

from e_infra.ports.provider import Isolation, Locality, ProviderSpec, Workload
from e_infra.ports.telemetry import SpanKind

if TYPE_CHECKING:
    from collections.abc import Generator, Mapping

    from e_infra.ports.telemetry import AttributeValue, SpanRole, SpanStatus


##### SPAN #####
class NullSpan:
    """A span that keeps nothing."""

    __slots__ = ()

    @property
    def trace_id(self) -> str:
        return ""

    @property
    def span_id(self) -> str:
        return ""

    ### the port's parameter names stay, so it lines up by shape — there is simply nothing to keep.
    def record(self, attributes: Mapping[str, AttributeValue]) -> None: ...

    def event(self, name: str, attributes: Mapping[str, AttributeValue]) -> None: ...

    def status(self, status: SpanStatus, description: str = "") -> None: ...


##### ADAPTER #####
class NullAdapter:
    """Telemetry off: spans that keep nothing, an empty carrier, a resume that changes nothing."""

    spec: ClassVar[ProviderSpec] = ProviderSpec("null", Locality.EMBEDDED, Workload.IO_BOUND, Isolation.LOOP)

    __slots__ = ()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Nothing was taken, nothing to release."""

    async def health(self) -> bool:
        return True

    @contextmanager
    def span(
        self,
        name: str,  # noqa: ARG002 — kept by nobody
        attributes: Mapping[str, AttributeValue],  # noqa: ARG002
        kind: SpanKind = SpanKind.INTERNAL,  # noqa: ARG002
        *,
        role: SpanRole | None = None,  # noqa: ARG002
    ) -> Generator[NullSpan]:
        yield NullSpan()

    def carrier(self) -> dict[str, str]:
        return {}

    @contextmanager
    def resume(self, carrier: Mapping[str, str]) -> Generator[None]:  # noqa: ARG002 — there is no trace to resume
        yield
