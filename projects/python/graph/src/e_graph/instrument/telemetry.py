"""instrument.telemetry: what the instrument measures, over whatever provider the app plugs in.

The instrument never names a vendor. `SpanTelemetry` is the provider contract — `span(name, attributes,
kind)`, a context manager yielding a `SpanPort` (ids, plus `record` / `event` / `status` while it is open) —
met *by shape*: any adapter whose class lines up plugs in, no inheritance (this app passes its OpenTelemetry
adapter, a singleton). `NullTelemetry` is the provider of no provider: spans are blocks that record nothing,
so the instrument runs untraced.

`InstrumentTelemetry` is the instrument's own face over that provider, built once and mounted as
`instrument.telemetry`: it knows *what* is traced — a run, each node inside it — and *how it reads*: the run
opens with its input and closes with its verdict (an ERROR status when it failed) and a snapshot of its
context — the run's data survives its release here, recoverable from the trace; each node closes with its
outcome: summary, the agent's token usage when it ran, and whatever extras the node reported. Attribute names follow the OpenInference conventions trace UIs render (`input.value`,
`output.value`, `openinference.span.kind`); the node and the graph never spell one."""

from collections.abc import Mapping
from contextlib import AbstractContextManager, contextmanager
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Protocol, runtime_checkable

import msgspec

from e_graph.instrument.models import NodeOutput, RunEnd, RunStatus
from e_graph.logic.models import SpecOutcome, SpecStatus
from ports.telemetry import AttributeValue, SpanKind, SpanPort, SpanStatus

if TYPE_CHECKING:
    from collections.abc import Generator

JSON: Final[str] = "application/json"
CHAIN: Final[Mapping[str, AttributeValue]] = MappingProxyType({"openinference.span.kind": "CHAIN"})
VERDICTS: Final[Mapping[RunStatus, SpanStatus]] = MappingProxyType(
    {
        RunStatus.SUCCEEDED: SpanStatus.OK,
        RunStatus.FAILED: SpanStatus.ERROR,
    }
)


##### PROVIDERS #####
@runtime_checkable
class SpanTelemetry(Protocol):
    """The provider contract: open a span around a block, hand back its live handle, record a raise and re-raise it."""

    def span(
        self, name: str, attributes: Mapping[str, AttributeValue], kind: SpanKind = SpanKind.INTERNAL
    ) -> AbstractContextManager[SpanPort]: ...


class NullSpan:
    """The span of no provider: no ids, and every write lands nowhere."""

    __slots__ = ()

    @property
    def trace_id(self) -> str:
        return ""

    @property
    def span_id(self) -> str:
        return ""

    ### the contract's parameter names stay, so it lines up by shape — there is simply nothing to keep.
    def record(self, attributes: Mapping[str, AttributeValue]) -> None:  # noqa: ARG002
        return

    def event(self, name: str, attributes: Mapping[str, AttributeValue]) -> None:  # noqa: ARG002
        return

    def status(self, status: SpanStatus, description: str = "") -> None:  # noqa: ARG002
        return


NO_SPAN: Final = NullSpan()


class NullTelemetry:
    """No provider: every span is an empty block — no ids, no export, nothing to configure."""

    __slots__ = ()

    @contextmanager
    def span(
        self,
        name: str,  # noqa: ARG002
        attributes: Mapping[str, AttributeValue],  # noqa: ARG002
        kind: SpanKind = SpanKind.INTERNAL,  # noqa: ARG002
    ) -> Generator[SpanPort]:
        yield NO_SPAN


##### FACADE #####
class InstrumentTelemetry:
    """What the instrument traces — a run, each node within it — and how each reads, over the given provider."""

    __slots__ = ("_provider",)

    def __init__(self, provider: SpanTelemetry | None = None) -> None:
        self._provider: SpanTelemetry = NullTelemetry() if provider is None else provider

    @staticmethod
    def _common_spell(value: object) -> object:
        """JSON's fallback: a nested mapping (a context's child State) by its items, anything else by its repr."""
        match value:
            case Mapping():
                return dict(value)
            case _:
                return repr(value)

    @classmethod
    def _common_json(cls, data: Mapping[str, object]) -> str:
        """A mapping as JSON, nested States included; nothing JSON cannot spell is ever dropped silently."""
        return msgspec.json.encode(dict(data), enc_hook=cls._common_spell, order="sorted").decode()

    ############################################################

    @property
    def provider(self) -> SpanTelemetry:
        """The plugged provider: the app's adapter, or `NullTelemetry` when none was given."""
        return self._provider

    def run(self, run_id: str, data: Mapping[str, object], correlation: str = "") -> AbstractContextManager[SpanPort]:
        """The span around a whole run, opened with the data it was seeded with; its nodes' spans nest under it.

        `correlation` is the request's correlation id: the access log line and the trace share it."""
        attributes = {
            **CHAIN,
            "run.id": run_id,
            "run.correlation_id": correlation,
            "input.value": self._common_json(data),
            "input.mime_type": JSON,
        }
        return self._provider.span("run", attributes)

    def node(self, name: str, category: str, role: str, run_id: str) -> AbstractContextManager[SpanPort]:
        """The span around one node call, named after the node and tagged with its place in the run."""
        attributes = {**CHAIN, "node.name": name, "node.category": category, "node.role": role, "run.id": run_id}
        return self._provider.span(f"node.{name}", attributes)

    def outcome(self, span: SpanPort, output: NodeOutput) -> None:
        """Close a node's span with what it did: its summary as output, the agent's tokens, the node's extras."""
        tokens = output.usage
        usage = (
            {}
            if tokens is None
            else {
                "llm.token_count.prompt": tokens.input_tokens,
                "llm.token_count.completion": tokens.output_tokens,
                "llm.token_count.total": tokens.total_tokens,
                "node.agent.calls": tokens.calls,
            }
        )
        extra = {"node.extra": self._common_json(output.extra)} if output.extra else {}
        span.record({"node.summary": output.summary, "output.value": output.summary, **usage, **extra})

    def spec(self, name: str, section: str, kind: str, run_id: str) -> AbstractContextManager[SpanPort]:
        """The span around one spec — or one fused call (`name` = the call, `kind` = `fused`) — inside its node."""
        attributes = {**CHAIN, "spec.name": name, "spec.section": section, "spec.kind": kind, "run.id": run_id}
        return self._provider.span(f"spec.{name}", attributes)

    def settle(self, span: SpanPort, outcome: SpecOutcome) -> None:
        """Close a spec's span with how it ended: status, step, latency, the fallback that rescued it, its error."""
        tokens = outcome.usage
        usage = (
            {} if tokens is None else {"llm.token_count.total": tokens.total_tokens, "spec.agent.calls": tokens.calls}
        )
        span.record(
            {
                "spec.status": outcome.status,
                "spec.step": outcome.step,
                "spec.latency_ms": outcome.latency_ms,
                "spec.reason": outcome.reason,
                "spec.rescuer": outcome.rescuer,
                "output.value": outcome.reason or outcome.status,
                **usage,
            }
        )
        span.status(
            SpanStatus.OK if outcome.status.delivered or outcome.status is SpecStatus.SKIPPED else SpanStatus.ERROR,
            outcome.error,
        )

    def verdict(self, span: SpanPort, end: RunEnd, context: Mapping[str, object]) -> None:
        """Close a run's span: verdict as output, the context as it stood (recoverable after its release), status."""
        span.record(
            {
                "run.status": end.status,
                "run.latency_ms": end.latency_ms,
                "run.context": self._common_json(context),
                "output.value": msgspec.json.encode(end).decode(),
                "output.mime_type": JSON,
            }
        )
        span.status(VERDICTS[end.status], end.error)
