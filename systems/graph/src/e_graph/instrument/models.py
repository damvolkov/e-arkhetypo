"""instrument.models: what the instrumented graph says about itself — node outputs and topology.

Two families, all msgspec and frozen: the `NodeOutput` every node emits (a receptacle of what
happened, never the workflow data — that lives in the RunState) and the `Topology` the graph derives
from its own declaration — a client-agnostic map any consumer draws from (the canvas places nodes by
rank and lane). Run frames (`NodeOutput`, `RunEnd`) form a tagged union: one socket, one decoder."""

from datetime import UTC, datetime
from enum import StrEnum, auto
from typing import Any

import msgspec

from e_graph.logic.models import Usage


##### STATUS #####
class NodeStatus(StrEnum):
    """A node's life in one run: pending until reached, skipped when the run ends without it."""

    PENDING = auto()
    RUNNING = auto()
    SUCCEEDED = auto()
    FAILED = auto()
    SKIPPED = auto()


class NodeRole(StrEnum):
    """Where a node sits in its graph, read off LangGraph's sentinels: wired from START, into END, or between.

    A node both entered from START and leading to END is END — it is the one whose output closes the run."""

    START = auto()
    END = auto()
    MID = auto()


class RunStatus(StrEnum):
    """A whole run's verdict."""

    SUCCEEDED = auto()
    FAILED = auto()


##### RUN FRAMES #####
class NodeOutput(msgspec.Struct, frozen=True, kw_only=True, tag="node"):
    """What happened in one node: identity, role, status, latency, summary, usage, the trace — and any extras.

    The instrument fills it; a node may hand back a partial one (or a dict) and the two merge — every slot
    the instrument left empty takes the node's value, so what the system measures (latency, status, ids,
    trace) always stands. `role` places the node against START/END, filled from the graph's own edges.
    `category` is a `Section` value for DARTS nodes, the folder name for a custom category. `summary` is the
    node's own sentence, its docstring headline otherwise. `usage` is what the agent spent inside the node,
    None when it never ran. `extra` carries whatever else the node chose to report — JSON-encodable values."""

    run_id: str = ""
    name: str = ""
    category: str = ""
    role: NodeRole = NodeRole.MID
    status: NodeStatus = NodeStatus.PENDING
    at: datetime = msgspec.field(default_factory=lambda: datetime.now(UTC))
    summary: str = ""
    latency_ms: float = 0.0
    error: str = ""
    trace_id: str = ""
    span_id: str = ""
    usage: Usage | None = None
    extra: dict[str, Any] = msgspec.field(default_factory=dict)


class RunEnd(msgspec.Struct, frozen=True, kw_only=True, tag="run"):
    """The closing frame of a run: its verdict, its latency, and the nodes it never reached."""

    run_id: str
    status: RunStatus
    latency_ms: float
    skipped: tuple[str, ...] = ()
    error: str = ""


type RunFrame = NodeOutput | RunEnd


class RunResult(msgspec.Struct, frozen=True, kw_only=True):
    """A batch run: every node's terminal output in emission order, and the closing verdict."""

    outputs: tuple[NodeOutput, ...]
    end: RunEnd


##### TOPOLOGY #####
class EdgeKind(StrEnum):
    """How an arc was declared: a plain edge, a branch of a router, or one leg of a fan-in join."""

    DIRECT = auto()
    CONDITIONAL = auto()
    JOIN = auto()


class TopologyNode(msgspec.Struct, frozen=True, kw_only=True):
    """One node placed on the grid: `rank` is the step (longest path from the entries), `lane` its slot."""

    id: str
    role: NodeRole
    category: str = ""
    summary: str = ""
    rank: int = 0
    lane: int = 0


class TopologyEdge(msgspec.Struct, frozen=True, kw_only=True):
    """One arc; `loop` marks a back edge — the one that closes a cycle against the flow."""

    id: str
    source: str
    target: str
    kind: EdgeKind = EdgeKind.DIRECT
    label: str = ""
    loop: bool = False


class Topology(msgspec.Struct, frozen=True, kw_only=True):
    """The whole declared graph: nodes on their grid, arcs between them, and the grid's extent.

    LangGraph's sentinels are not vertices here: each node's `role` already says where START and END are."""

    nodes: tuple[TopologyNode, ...]
    edges: tuple[TopologyEdge, ...]
    ranks: int
    lanes: int
