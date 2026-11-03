"""engines/telemetry: what a service traces, guarded — the facade every module reaches, over one `TelemetryPort`.

A span has a name, a `SpanRole` and attributes keyed by `SpanKey` or a free dotted name; the provider translates them.
The facade is guarded: a provider that raises — on open, on a write, on close — costs a warning and the trace, never the
call it wraps; with no provider every call is a no-op. The span open in the current task is a context variable, so a
log line written inside it becomes one of its events (`TelemetryEngine.processor`, given to the logger's chain by the
composition root) and carries its ids. `carrier`/`resume` move a trace across a queue as an opaque mapping: empty
outside a span, ignored when empty."""

from contextlib import AbstractContextManager, contextmanager
from contextvars import ContextVar
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from e_infra.infra.logger import logger

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Mapping, MutableMapping

    from e_infra.ports.telemetry import AttributeValue, SpanPort, SpanRole, SpanStatus, TelemetryPort

    type Opened = tuple[AbstractContextManager[SpanPort], SpanPort]

### the facade's own warning: the processor below leaves it alone, so a failing provider never loops through itself.
FAILED: Final[str] = "telemetry failed"
NOTHING: Final[Mapping[str, AttributeValue]] = MappingProxyType({})
### the span open in the current task, as the provider gave it: None outside any span or without a provider.
CURRENT: ContextVar[SpanPort | None] = ContextVar("telemetry_span", default=None)


class TelemetryEngine:
    """The guarded facade over one provider (None: tracing off): spans opened through it, writes on the current one."""

    __slots__ = ("_provider",)

    def __init__(self, provider: TelemetryPort | None = None) -> None:
        self._provider = provider

    ##### PRIVATE #####

    @staticmethod
    def _common_plain(value: object) -> AttributeValue:
        return value if isinstance(value, str | bool | int | float) else str(value)

    @staticmethod
    def _common_warn(what: str, error: Exception) -> None:
        logger.warning(FAILED, what=what, error=f"{type(error).__name__}: {error}")

    def _span_open(self, name: str, role: SpanRole, attributes: Mapping[str, AttributeValue]) -> Opened | None:
        """The provider's span opened and entered; None without a provider or when it fails."""
        match self._provider:
            case None:
                return None
            case provider:
                try:
                    manager = provider.span(name, attributes, role=role)
                    return manager, manager.__enter__()
                except Exception as error:  # noqa: BLE001 — telemetry never fails the service
                    self._common_warn("span open", error)
                    return None

    def _span_close(self, opened: Opened | None, error: BaseException | None) -> None:
        match opened:
            case None:
                return
            case (manager, _):
                exit_args = (type(error), error, error.__traceback__) if error else (None, None, None)
                self.guard("span close", lambda: manager.__exit__(*exit_args))

    def _resume_open(self, carrier: Mapping[str, str]) -> AbstractContextManager[None] | None:
        """The provider's resume entered; None without a provider, without a carrier, or when it fails."""
        match self._provider:
            case None:
                return None
            case _ if not carrier:
                return None
            case provider:
                try:
                    manager = provider.resume(carrier)
                    manager.__enter__()
                except Exception as error:  # noqa: BLE001 — telemetry never fails the service
                    self._common_warn("resume", error)
                    return None
                return manager

    ############################################################

    ##### PUBLIC #####

    @classmethod
    def guard(cls, what: str, call: Callable[[], Any]) -> Any:
        """Run a provider call; a failure is said once and answered None."""
        try:
            return call()
        except Exception as error:  # noqa: BLE001 — telemetry never fails the service
            cls._common_warn(what, error)
            return None

    @contextmanager
    def span(self, name: str, role: SpanRole, attributes: Mapping[str, AttributeValue] = NOTHING) -> Generator[None]:
        """A span around the block, current inside it; a provider failure leaves the block untraced, never failed."""
        opened = self._span_open(name, role, attributes)
        token = CURRENT.set(opened[1] if opened else None)
        try:
            yield
        except BaseException as error:
            CURRENT.reset(token)
            self._span_close(opened, error)
            raise
        CURRENT.reset(token)
        self._span_close(opened, None)

    def record(self, attributes: Mapping[str, AttributeValue]) -> None:
        """Attributes on the current span, known once the work ran."""
        match CURRENT.get():
            case None:
                return
            case span:
                self.guard("record", lambda: span.record(attributes))

    def event(self, name: str, attributes: Mapping[str, object]) -> None:
        """A timestamped point on the current span; values a provider cannot hold are written as text."""
        match CURRENT.get():
            case None:
                return
            case span:
                plain = {key: self._common_plain(value) for key, value in attributes.items() if value is not None}
                self.guard("event", lambda: span.event(name, plain))

    def status(self, status: SpanStatus, description: str = "") -> None:
        match CURRENT.get():
            case None:
                return
            case span:
                self.guard("status", lambda: span.status(status, description))

    def carrier(self) -> dict[str, str]:
        """The current trace as an opaque mapping to send along; empty without a provider or a span."""
        match self._provider:
            case None:
                return {}
            case _ if CURRENT.get() is None:
                return {}
            case provider:
                return dict(self.guard("carrier", provider.carrier) or {})

    @contextmanager
    def resume(self, carrier: Mapping[str, str]) -> Generator[None]:
        """Run the block as the child of `carrier`'s trace; an empty or unreadable carrier starts none."""
        resumed = self._resume_open(carrier)
        try:
            yield
        finally:
            match resumed:
                case None:
                    pass
                case manager:
                    self.guard("resume exit", lambda: manager.__exit__(None, None, None))

    @classmethod
    def processor(cls, _: object, __: str, event_dict: MutableMapping[str, Any]) -> Mapping[str, Any]:
        """structlog: a log line inside a span becomes one of its events and carries its ids; outside, untouched."""
        name = str(event_dict.get("event", ""))
        match CURRENT.get():
            case None:
                return event_dict
            case _ if name == FAILED:
                return event_dict
            case span:
                fields = {key: value for key, value in event_dict.items() if key != "event" and value is not None}
                cls.guard("log event", lambda: span.event(name, {k: cls._common_plain(v) for k, v in fields.items()}))
                ids = cls.guard("ids", lambda: {"trace_id": span.trace_id, "span_id": span.span_id})
                return {**event_dict, **(ids or {})}
