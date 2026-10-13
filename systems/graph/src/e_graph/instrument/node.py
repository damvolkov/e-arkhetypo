"""instrument.node: InstrumentNode — LangGraph's own node spec, narrowed to one contract and instrumented.

Two contracts, one per side. The user's *function* is exactly
`async def node_<name>(state: RunState) -> NodeResult`, defined in `nodes/<category>/node.py` — it types
the RunState and nothing else, and may report what it did: a `str` is its summary; a `dict` fills the
output's slots by name (`summary`, `usage`…) and carries every other key as `extra`; a `NodeOutput` (even
a partial one) merges the same way; `None` reports nothing. The *node* wraps it and always answers
`RunState → NodeOutput`: a RUNNING frame and a log line on entry; a telemetry span, a latency meter and
the agent's usage meter around the call; a SUCCEEDED or FAILED `NodeOutput` streamed, logged and returned
on exit — a raise never escapes, it becomes the FAILED output. The merge only fills slots the instrument
left empty: what the system measures (status, latency, ids, trace) always stands, and `usage` is what the
agent spent inside the node unless the node reports its own. The function is checked while the graph is
declared, so a broken node never compiles. The node is a real `StateNodeSpec` subclass LangGraph compiles
untouched; LangGraph's channels are the graph's business, which bridges them to `run` and turns a FAILED
output into the NodeError that stops (or retries) the run."""

import inspect
import re
from annotationlib import Format
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from types import MappingProxyType, NoneType, UnionType
from typing import Any, Final, Self, Union, cast, get_args, get_origin, get_type_hints

import msgspec
from langgraph.config import get_stream_writer
from langgraph.graph._node import StateNodeSpec
from langgraph.types import StreamWriter

from adapters.ports import SpanPort
from core.logger import logger
from e_graph.instrument.errors import ContractError, ContractRule
from e_graph.instrument.models import NodeOutput, NodeRole, NodeStatus
from e_graph.instrument.state import Channels, RunState
from e_graph.instrument.telemetry import NO_SPAN
from e_graph.logic.agent import AgnosticAgent
from e_graph.logic.models import Usage
from e_graph.models.section import Section
from ops.wrappers import LatencyWrapper

type NodeResult = str | dict[str, Any] | NodeOutput | None
type NodeFunc = Callable[[RunState], Awaitable[NodeResult]]

FUNC_RE: Final = re.compile(r"^node_(?P<name>[a-z][a-z0-9_]*)$")
LOCATION_RE: Final = re.compile(r"(?:^|\.)nodes\.(?P<category>[a-z][a-z0-9_]*)\.node$")
### what a node may hand back, member by member: `str | dict[str, Any] | NodeOutput | None` or any part of it.
RETURNS: Final[frozenset[type]] = frozenset({NoneType, str, dict, NodeOutput})
UNIONS: Final[frozenset[object]] = frozenset({Union, UnionType})
FIELDS: Final[frozenset[str]] = frozenset(NodeOutput.__struct_fields__)
### the slots a node's report cannot fill because the instrument always has: what it measures, never what it's told.
EMPTY: Final[tuple[object, ...]] = (None, "", {})
SECTIONS: Final[frozenset[str]] = frozenset(Section)
LEVELS: Final[Mapping[NodeStatus, str]] = MappingProxyType(
    {
        NodeStatus.RUNNING: "info",
        NodeStatus.SUCCEEDED: "info",
        NodeStatus.FAILED: "error",
    }
)


##### NODE #####
@dataclass(slots=True, kw_only=True)
class InstrumentNode(StateNodeSpec[Channels, None]):
    """A LangGraph node spec that knows its function, name, category and headline, and runs instrumented."""

    func: NodeFunc
    name: str
    category: str
    doc: str
    ### the graph fills it at compile time, from its edges to and from LangGraph's START/END sentinels.
    role: NodeRole = NodeRole.MID

    @staticmethod
    def _validate_hints(func: Callable[..., object]) -> dict[str, Any]:
        """Resolved annotations; an unresolvable one reads as absent, so the STATE/RETURN rule names it."""
        try:
            return get_type_hints(func)
        except NameError:
            return {}

    @staticmethod
    def _validate_async(func: Callable[..., object]) -> bool:
        return inspect.iscoroutinefunction(func)

    @staticmethod
    def _validate_name(func: Callable[..., object]) -> bool:
        return FUNC_RE.match(getattr(func, "__name__", "")) is not None

    @staticmethod
    def _validate_location(func: Callable[..., object]) -> bool:
        return LOCATION_RE.search(getattr(func, "__module__", "")) is not None

    @staticmethod
    def _validate_signature(func: Callable[..., object]) -> bool:
        params = tuple(inspect.signature(func, annotation_format=Format.FORWARDREF).parameters.values())
        return len(params) == 1 and params[0].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD

    @classmethod
    def _validate_state(cls, func: Callable[..., object]) -> bool:
        param = next(iter(inspect.signature(func, annotation_format=Format.FORWARDREF).parameters))
        return isinstance(hint := cls._validate_hints(func).get(param), type) and issubclass(hint, RunState)

    @classmethod
    def _validate_return(cls, func: Callable[..., object]) -> bool:
        hint = cls._validate_hints(func).get("return", inspect.Parameter.empty)
        members = get_args(hint) if get_origin(hint) in UNIONS else (hint,)
        ### a parametrized member (`dict[str, Any]`) counts by its origin; a bare one by itself.
        return all((get_origin(member) or member) in RETURNS for member in members)

    def _run_output(
        self,
        state: RunState,
        status: NodeStatus,
        *,
        span: SpanPort = NO_SPAN,
        latency_ms: float = 0.0,
        error: str = "",
        usage: Usage | None = None,
    ) -> NodeOutput:
        return NodeOutput(
            run_id=state.id,
            name=self.name,
            category=self.category,
            role=self.role,
            status=status,
            at=datetime.now(UTC),
            latency_ms=latency_ms,
            error=error,
            trace_id=span.trace_id,
            span_id=span.span_id,
            usage=usage,
        )

    @staticmethod
    def _run_payload(result: NodeResult) -> dict[str, Any]:
        """What the node reported, as slots by name: a sentence is the summary, a NodeOutput its own fields."""
        match result:
            case None:
                return {}
            case str():
                return {"summary": result}
            case NodeOutput():
                return msgspec.structs.asdict(result)
            case dict():
                return dict(result)
            case other:
                msg = f"a node returns str | dict | NodeOutput | None, not {type(other).__name__}"
                raise TypeError(msg)

    def _run_merge(self, base: NodeOutput, payload: dict[str, Any]) -> NodeOutput:
        """The node's report folded into the instrument's output: only empty slots take it, the rest is `extra`."""
        named = {key: value for key, value in payload.items() if key in FIELDS and key != "extra"}
        filled = {key: value for key, value in named.items() if getattr(base, key) in EMPTY}
        extra = {**base.extra, **payload.get("extra", {}), **{k: v for k, v in payload.items() if k not in FIELDS}}
        summary = filled.pop("summary", "") or base.summary or self.doc
        return msgspec.convert(msgspec.structs.asdict(base) | filled | {"summary": summary, "extra": extra}, NodeOutput)

    @staticmethod
    def _run_discard(_frame: object) -> None:
        """The stream outside a run: nothing listens, the frame already reached the log."""

    @classmethod
    def _run_writer(cls) -> StreamWriter:
        """LangGraph's stream inside a run; outside one (a direct call) there is no stream, frames go to the log only."""
        try:
            return get_stream_writer()
        except RuntimeError:
            return cls._run_discard

    def _run_emit(self, emit: StreamWriter, output: NodeOutput, error: BaseException | None = None) -> NodeOutput:
        """One frame, two sinks: the custom stream (the canvas) and the structured log, traceback included."""
        emit(output)
        getattr(logger, LEVELS[output.status])(
            f"node {output.status}", exc_info=error, **msgspec.structs.asdict(output)
        )
        return output

    ############################################################

    @classmethod
    def validate(cls, func: Callable[..., object]) -> str:
        """Check every law against `func`; the name it derives (`node_extract` → `extract`) on success."""
        ### ordered: each law only runs once the earlier ones held, so later checks may assume them.
        rules: tuple[tuple[ContractRule, Callable[[Callable[..., object]], bool], str], ...] = (
            (ContractRule.ASYNC, cls._validate_async, "must be `async def`"),
            (ContractRule.NAME, cls._validate_name, "must be named `node_<name>`"),
            (ContractRule.LOCATION, cls._validate_location, "must live in `nodes/<category>/node.py`"),
            (ContractRule.SIGNATURE, cls._validate_signature, "must take exactly one positional parameter"),
            (ContractRule.STATE, cls._validate_state, "its parameter must be annotated `RunState`"),
            (ContractRule.RETURN, cls._validate_return, "must return `NodeResult`: str | dict | NodeOutput | None"),
        )
        subject = getattr(func, "__qualname__", repr(func))
        match next(((rule, detail) for rule, holds, detail in rules if not holds(func)), None):
            case (rule, detail):
                raise ContractError(rule, subject, detail)
            case _:
                ### every law held, NAME among them: the match exists, the group is the derived name.
                return cast("re.Match[str]", FUNC_RE.fullmatch(getattr(func, "__name__", "")))["name"]

    @classmethod
    def wrap(cls, spec: StateNodeSpec[Any, Any], func: NodeFunc, name: str) -> Self:
        """Promote the spec LangGraph built for `func` into an InstrumentNode; the graph bridges its runnable."""
        ### validate ran before wrap: the location matched, the group is the category folder.
        raw = cast("re.Match[str]", LOCATION_RE.search(func.__module__))["category"]
        headline = (inspect.getdoc(func) or "").partition("\n")[0]
        return cls(
            **{field.name: getattr(spec, field.name) for field in fields(StateNodeSpec)},
            func=func,
            name=name,
            category=Section(raw) if raw in SECTIONS else raw,
            doc=headline,
        )

    async def run(self, state: RunState) -> NodeOutput:
        """The instrumented call, always answered with a NodeOutput — SUCCEEDED, or FAILED carrying the error.

        RUNNING goes out first; the function then runs inside a telemetry span (which records a raise), a
        latency meter and the agent's usage meter. Its report merges into the output, which closes the span.
        A raise never escapes: it becomes the FAILED output — usage included, tokens spent before the failure
        still count — its traceback goes to the log, and whether the run stops is the graph's business."""
        emit, span, telemetry = self._run_writer(), NO_SPAN, state.infra.telemetry
        self._run_emit(emit, self._run_output(state, NodeStatus.RUNNING))
        with LatencyWrapper() as latency, AgnosticAgent.meter() as meter:
            try:
                with telemetry.node(self.name, self.category, self.role, state.id) as span:
                    result = await self.func(state)
                    base = self._run_output(state, NodeStatus.SUCCEEDED, span=span, usage=meter.usage)
                    drafted = self._run_merge(base, self._run_payload(result))
                    telemetry.outcome(span, drafted)
            except Exception as error:  # noqa: BLE001 — the failure is the output; the graph decides what it stops
                failure = f"{type(error).__name__}: {error}"
                failed = self._run_output(
                    state, NodeStatus.FAILED, span=span, latency_ms=latency.ms, error=failure, usage=meter.usage
                )
                return self._run_emit(emit, failed, error)
        return self._run_emit(emit, msgspec.structs.replace(drafted, latency_ms=latency.ms))
