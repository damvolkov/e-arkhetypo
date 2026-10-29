"""instrument.state: the RunState every node receives — the app's branches that live with the app, `context` that
lives with the run — and the instrument's own branch, `InstrumentState`.

Two zones, never mixed. The app's singletons, sealed at startup and shared by every run, are the system's branches
under the same names: `infra.adapters` (every external edge), `infra.processors` (the readers over them,
`processors.doc`), `infra.graphs` (every built pipeline), `logic.agent` (the agnostic agent), `logic.orchestrator`
(the DARTS engine) and `instrument.telemetry` (the instrument's tracer). `context` is everything one request
produces — ephemeral, owned by its run id. Contexts live in one process-wide store, `instrument.contexts`, as
`context.<id>`; a `RunState` is a run's view of the app: its `id`, the shared branches, and its own
`context` already scoped to that id, so nodes write `state.context.amount = …` and never spell the id.

A run's context is released when the run closes — the instrument does it, by default, for every graph
that reaches END or fails — so the store never grows with finished runs; the run span keeps a snapshot.

LangGraph never sees the inside: its state schema is `Channels`, a `run` field holding the RunState *by
reference* (nodes mutate its context in place, no reducer, no copy) and an append-only `outputs` field
where every node lands its `NodeOutput` — the batch result reads it back."""

import operator
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from typing import TYPE_CHECKING, Annotated, Final, TypedDict, cast

from adapters.base import AdapterPing, BaseAdapter
from adapters.ports import DocumentPort, HttpPort, StorePort, TelemetryPort
from e_graph.instrument.contexts import InstrumentContexts
from e_graph.instrument.models import NodeOutput
from infra.state import State

if TYPE_CHECKING:
    from datetime import timedelta

    ### annotation only: each sits above this module — it imports this one at runtime, or lives in a higher layer.
    from e_graph.instrument.graph import InstrumentGraph
    from e_graph.instrument.telemetry import InstrumentTelemetry
    from e_graph.logic.state import LogicState
    from processors.doc import DocProcessor

### the edges a ready service cannot do without; a role not here is optional.
REQUIRED: Final[frozenset[str]] = frozenset({"store"})


##### INFRA #####
@dataclass(frozen=True, slots=True)
class AdaptersState:
    """The typed adapters section: fields named by role, typed by the port the role speaks.

    `store` is the KV edge the app's records live on; `telemetry` is the raw provider whose lifecycle the
    exit stack owns — the instrument reaches it only through `instrument.telemetry`; `docling` converts documents
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
    """The infrastructure a run may use: built once at startup, shared by every run, mutated by none."""

    adapters: AdaptersState
    processors: ProcessorsState
    graphs: Mapping[str, InstrumentGraph]


##### BRANCH #####
@dataclass(frozen=True, slots=True)
class InstrumentState:
    """The instrument's branch, `system.instrument`: one attribute per module of `instrument/` the app holds alive —
    the tracer every run and node reports through, and the store of live runs' contexts."""

    telemetry: InstrumentTelemetry
    contexts: InstrumentContexts


##### RUN STATE #####
class RunState(State):
    """One run's view of the app: its `id`, the request it came from, the shared branches, its own `context`.

    The run id is minted here, never taken from the request: the correlation id is client-controlled
    (`X-Request-ID`), so two requests may share it; the run keeps it only as a link."""

    __slots__ = ()

    def __init__(self, system: State, run_id: str = "", correlation: str = "", pipeline: str = "") -> None:
        identity = run_id or uuid.uuid7().hex
        cast("InstrumentState", system.instrument).contexts.open(identity)
        super().__init__(
            id=identity,
            correlation=correlation,
            pipeline=pipeline,
            infra=system.infra,
            logic=system.logic,
            instrument=system.instrument,
        )
        ### only this level seals: the context stays open for the nodes, the branches were sealed by the lifespan.
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
        """The app's infrastructure: adapters, processors, graphs."""
        return cast("InfraState", self["infra"])

    @property
    def logic(self) -> LogicState:
        """The logic's singletons: the agent and the orchestrator."""
        return cast("LogicState", self["logic"])

    @property
    def instrument(self) -> InstrumentState:
        """The instrument's singletons: the tracer and the contexts store."""
        return cast("InstrumentState", self["instrument"])

    @property
    def context(self) -> State:
        """This run's ephemeral zone — everything the workflow produces lives here, under the run's id."""
        return self.instrument.contexts[self.id]

    def release(self) -> None:
        """Drop this run's context from the store: the run is over, its data has nowhere left to go."""
        self.instrument.contexts.drop(self.id)


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
