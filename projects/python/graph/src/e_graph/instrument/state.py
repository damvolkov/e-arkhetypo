"""instrument.state: the RunState every node receives — `infra` that lives with the app, `context` that lives with the run.

Two zones, never mixed. `infra` is the app's singletons, sealed at startup and shared by every run:
`infra.adapters` (every external edge), `infra.processors` (the readers over them, `processors.doc`), `infra.agent` (the agnostic agent), `infra.telemetry` (the
instrument's tracer) and `infra.graphs` (every built pipeline). `context` is everything one request
produces — ephemeral, owned by its run id. Contexts live in one process-wide store, `ContextState`, as
`context.<id>`; a `RunState` is a run's view of the app: its `id`, the shared `infra`, and its own
`context` already scoped to that id, so nodes write `state.context.amount = …` and never spell the id.

A run's context is released when the run closes — the instrument does it, by default, for every graph
that reaches END or fails — so the store never grows with finished runs; the run span keeps a snapshot.

LangGraph never sees the inside: its state schema is `Channels`, a `run` field holding the RunState *by
reference* (nodes mutate its context in place, no reducer, no copy) and an append-only `outputs` field
where every node lands its `NodeOutput` — the batch result reads it back."""

import operator
import uuid
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field, fields
from typing import TYPE_CHECKING, Annotated, Final, TypedDict, cast

from adapters.base import AdapterPing, BaseAdapter
from adapters.ports import DocumentPort, HttpPort, StorePort, TelemetryPort
from core.state import State
from e_graph.instrument.models import NodeOutput

if TYPE_CHECKING:
    from datetime import timedelta

    ### annotation only: these modules import this one at runtime, never the other way round.
    from e_graph.instrument.graph import InstrumentGraph
    from e_graph.instrument.telemetry import InstrumentTelemetry
    from e_graph.logic.agent import AgnosticAgent
    from e_graph.logic.orchestrator.core import OrchestratorCore
    from processors.doc import DocProcessor

### the edges a ready service cannot do without; a role not here is optional.
REQUIRED: Final[frozenset[str]] = frozenset({"store"})


##### INFRA #####
@dataclass(frozen=True, slots=True)
class AdaptersState:
    """The typed adapters section: fields named by role, typed by the port the role speaks.

    `store` is the KV edge the app's records live on; `telemetry` is the raw provider whose lifecycle the
    exit stack owns — the instrument reaches it only through `infra.telemetry`; `docling` converts documents
    (the DocProcessor drives it). Any further field is an optional edge the export may drop."""

    store: StorePort
    telemetry: TelemetryPort
    redis: StorePort
    http: HttpPort
    docling: DocumentPort

    async def ping(self, limit: timedelta) -> tuple[AdapterPing, ...]:
        """Every edge pinged at once, each within `limit`, in field order; the REQUIRED ones decide readiness."""
        ### every field is a concrete adapter behind its port, and every adapter pings.
        named = {each.name: cast("BaseAdapter", getattr(self, each.name)) for each in fields(self)}
        return await BaseAdapter.survey(named, limit, REQUIRED)


@dataclass(frozen=True, slots=True)
class ProcessorsState:
    """The typed processors section: stateless readers over the adapters — `doc` reads documents, hybrid."""

    doc: DocProcessor


@dataclass(frozen=True, slots=True)
class InfraState:
    """Every singleton a run may use: built once at startup, shared by every run, mutated by none."""

    adapters: AdaptersState
    processors: ProcessorsState
    agent: AgnosticAgent
    orchestrator: OrchestratorCore
    telemetry: InstrumentTelemetry
    graphs: Mapping[str, InstrumentGraph]


##### CONTEXT #####
class ContextState(Mapping[str, State]):
    """The process-wide store of live runs' contexts, `context.<id>`: opened by a run, released when it closes.

    Not a core `State` on purpose: sealing the app's graph at startup freezes `infra`, while this store
    must keep taking and dropping runs for the app's whole life."""

    __slots__ = ("_runs",)

    def __init__(self) -> None:
        self._runs: dict[str, State] = {}

    def __getitem__(self, run_id: str) -> State:
        return self._runs[run_id]

    def __iter__(self) -> Iterator[str]:
        return iter(self._runs)

    def __len__(self) -> int:
        return len(self._runs)

    ############################################################

    def open(self, run_id: str) -> State:
        """A fresh, empty context for a new run; an id already live is a wiring bug, never a silent share."""
        match run_id in self._runs:
            case True:
                msg = f"context {run_id!r} is already open: run ids are unique"
                raise ValueError(msg)
            case _:
                context = self._runs[run_id] = State()
                return context

    def drop(self, run_id: str) -> None:
        """Forget a run's context; dropping one already gone is a no-op."""
        self._runs.pop(run_id, None)


##### RUN STATE #####
class RunState(State):
    """One run's view of the app: its `id`, the request it came from, the shared `infra`, its own `context`.

    The run id is minted here, never taken from the request: the correlation id is client-controlled
    (`X-Request-ID`), so two requests may share it; the run keeps it only as a link."""

    __slots__ = ()

    def __init__(self, system: State, run_id: str = "", correlation: str = "", pipeline: str = "") -> None:
        identity = run_id or uuid.uuid7().hex
        contexts = cast("ContextState", system.contexts)
        contexts.open(identity)
        super().__init__(id=identity, correlation=correlation, pipeline=pipeline, infra=system.infra, contexts=contexts)
        ### only this level seals: the context stays open for the nodes, infra was sealed by the lifespan.
        object.__setattr__(self, "_sealed", True)

    ############################################################

    @property
    def id(self) -> str:
        """The run's identity, a UUIDv7 hex unless the caller named it — the key of its context."""
        return cast("str", self["id"])

    @property
    def correlation(self) -> str:
        """The request that started the run (its correlation id), empty outside a request; links log to trace."""
        return cast("str", self["correlation"])

    @property
    def pipeline(self) -> str:
        """The pipeline the run executes — where the orchestrator finds its specs and runners; empty outside one."""
        return cast("str", self["pipeline"])

    @property
    def infra(self) -> InfraState:
        """The app's singletons: adapters, agent, telemetry, graphs."""
        return cast("InfraState", self["infra"])

    @property
    def context(self) -> State:
        """This run's ephemeral zone — everything the workflow produces lives here, under the run's id."""
        return cast("ContextState", self["contexts"])[self.id]

    def release(self) -> None:
        """Drop this run's context from the store: the run is over, its data has nowhere left to go."""
        cast("ContextState", self["contexts"]).drop(self.id)


##### CHANNELS #####
@dataclass(frozen=True, slots=True)
class Channels:
    """LangGraph's state schema: the RunState by reference, and the append-only node outputs.

    A dataclass, not a TypedDict: LangGraph rebuilds it per node call, and type checkers can prove a
    dataclass satisfies LangGraph's state bound — a TypedDict they cannot."""

    run: RunState
    outputs: Annotated[list[NodeOutput], operator.add] = field(default_factory=list)


class ChannelUpdate(TypedDict):
    """What an instrumented node writes back: its own output, appended."""

    outputs: list[NodeOutput]
