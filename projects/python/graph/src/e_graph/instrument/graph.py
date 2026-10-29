"""instrument.graph: InstrumentGraph — a LangGraph StateGraph whose nodes are InstrumentNodes, and that knows its shape.

The builder keeps LangGraph's whole surface and semantics (START/END, fan-out, fan-in joins,
routers, loops, policies); it narrows what enters and adds what the platform needs on top:

- `add_node(node_extract)` derives the name `extract`; every node is checked against the contract
  and promoted to an `InstrumentNode`. `add_sequence` follows the same naming.
- `add_conditional_edges` takes routers over the `RunState`, sync or async, and refuses one whose
  targets are unknown — a `Literal[...]` return or an explicit `path_map` — so the topology is total.
- `topology` derives the declared graph on rustworkx: back edges found by DFS from START mark the
  loops, the remaining DAG is cut into generations (the rank: a step, longest path from the sources),
  and each rank is ordered by the barycenter of its parents (the lane), which keeps the drawing uncrossed.
- `stream` runs a compiled graph and yields the run frames — every `NodeOutput` as it happens, then a
  `RunEnd` naming the verdict and the nodes never reached; `run` is the same, collected for batch.
"""

import inspect
import itertools
import re
import statistics
import typing
from collections.abc import AsyncIterator, Awaitable, Callable, Hashable, Mapping, Sequence
from datetime import timedelta
from types import MappingProxyType
from typing import Any, Final, Self, TypedDict, Unpack, cast, get_args, get_origin, get_type_hints

import rustworkx as rx
from langgraph._internal._runnable import coerce_to_runnable
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import CachePolicy, RetryPolicy, TimeoutPolicy

from e_graph.instrument.errors import ContractError, ContractRule, NodeError
from e_graph.instrument.models import (
    EdgeKind,
    NodeOutput,
    NodeRole,
    NodeStatus,
    RunEnd,
    RunFrame,
    RunResult,
    RunStatus,
    Topology,
    TopologyEdge,
    TopologyNode,
)
from e_graph.instrument.node import InstrumentNode, NodeFunc
from e_graph.instrument.state import Channels, ChannelUpdate, RunState
from e_graph.models.section import Section
from infra.logger import logger
from ops.wrappers import LatencyWrapper

type Route = Callable[[RunState], Hashable | Awaitable[Hashable]]
type Arc = tuple[str, str, EdgeKind, str]

NAME_RE: Final = re.compile(r"^[a-z][a-z0-9_]*$")
### keyed by (leads into END, entered from START): END wins a tie — its output is the one that closes the run.
EDGE_ROLES: Final[Mapping[tuple[bool, bool], NodeRole]] = MappingProxyType(
    {
        (True, True): NodeRole.END,
        (True, False): NodeRole.END,
        (False, True): NodeRole.START,
        (False, False): NodeRole.MID,
    }
)
TERMINAL: Final[frozenset[NodeStatus]] = frozenset({NodeStatus.SUCCEEDED, NodeStatus.FAILED})


class NodePolicies(TypedDict, total=False):
    """The LangGraph node policies an InstrumentNode keeps; schema and error-handler stay the instrument's."""

    defer: bool
    metadata: dict[str, Any]
    retry_policy: RetryPolicy | Sequence[RetryPolicy]
    cache_policy: CachePolicy
    timeout: float | timedelta | TimeoutPolicy


##### VISITOR #####
class BackEdgeVisitor(rx.visit.DFSVisitor[object]):
    """Collects the arcs a DFS meets against its own stack — exactly the arcs that close a cycle."""

    def __init__(self) -> None:
        self.found: set[tuple[int, int]] = set()

    def back_edge(self, e: tuple[int, int, object]) -> None:
        self.found.add((e[0], e[1]))


##### GRAPH #####
class InstrumentGraph(StateGraph[Channels, None, Channels, Channels]):
    """LangGraph's builder over `Channels`, admitting InstrumentNodes only, aware of its own topology."""

    def __init__(self, name: str = "", summary: str = "", seed: dict[str, Any] | None = None) -> None:
        super().__init__(Channels)
        ### identity a builder stamps on the graph it builds: how the registry, the API and the canvas name it.
        self.name = name
        self.summary = summary
        self.seed = seed or {}
        self._compiled: CompiledStateGraph[Channels, None, Channels, Channels] | None = None

    def _add_resolve(self, node: str | NodeFunc, action: NodeFunc | None) -> tuple[str, NodeFunc]:
        """The node's name and function: derived from `node_<name>`, or given — and then a plain identifier."""
        match (node, action):
            case (str() as name, func) if func is not None and NAME_RE.fullmatch(name):
                InstrumentNode.validate(func)
                return name, func
            case (str() as name, func) if func is not None:
                raise ContractError(ContractRule.NAME, name, "a node name is a lowercase identifier")
            case (func, None) if callable(func):
                return InstrumentNode.validate(func), cast("NodeFunc", func)
            case _:
                raise ContractError(ContractRule.SIGNATURE, repr(node), "pass `node_<name>` or `(name, node_<name>)`")

    def _add_one(self, node: str | NodeFunc, action: NodeFunc | None, policies: NodePolicies) -> str:
        """Resolve, let LangGraph build its spec, promote it: the single road every node takes in."""
        name, func = self._add_resolve(node, action)
        ### LangGraph builds its spec around the bare function (RunState in) only for wrap to swap the runnable.
        super().add_node(name, cast("Any", func), input_schema=Channels, **policies)
        instrumented = InstrumentNode.wrap(self.nodes[name], func, name)
        self._add_own(instrumented)
        ### LangGraph schedules the bridge, never the bare function: channels in, the node's output appended.
        instrumented.runnable = coerce_to_runnable(self._add_channel(instrumented), name=name, trace=False)
        self.nodes[name] = instrumented
        return name

    def _add_own(self, node: InstrumentNode) -> None:
        """A pipeline's graph (a named one) mounts only its own pipeline's nodes, one per category: a section has one node."""
        taken = {other.category for other in self._common_instrumented().values()}
        match (self.name, node.pipeline == self.name, node.category in taken):
            case ("", _, _) | (_, True, False):
                return
            case (own, False, _):
                msg = f"belongs to pipeline {node.pipeline!r}: graph {own!r} mounts only pipelines/{own}/nodes"
                raise ContractError(ContractRule.PIPELINE, node.name, msg)
            case _:
                msg = f"category {node.category!r} already has its node: one node per section"
                raise ContractError(ContractRule.SECTION, node.name, msg)

    @staticmethod
    def _add_channel(node: InstrumentNode) -> Callable[[Channels], Awaitable[ChannelUpdate]]:
        """The node as LangGraph calls it: the RunState handed over, a FAILED output turned into a NodeError."""

        async def channel(channels: Channels) -> ChannelUpdate:
            match await node.run(channels.run):
                case NodeOutput(status=NodeStatus.FAILED) as failed:
                    raise NodeError(failed)
                case output:
                    return {"outputs": [output]}

        return channel

    @staticmethod
    def _route_ends(path: Route, path_map: dict[Hashable, str] | Sequence[str] | None) -> dict[Hashable, str]:
        """Every target a router can reach: its explicit map, or its `Literal[...]` return — never unknown."""
        match path_map:
            case dict():
                return dict(path_map)
            case None:
                hint = get_type_hints(path).get("return")
                match get_origin(hint):
                    case typing.Literal:
                        return {target: target for target in get_args(hint)}
                    case _:
                        subject = getattr(path, "__qualname__", repr(path))
                        raise ContractError(ContractRule.ROUTE, subject, "return `Literal[...]` or pass `path_map`")
            case targets:
                return {target: target for target in targets}

    @staticmethod
    def _route_wrap(path: Route) -> Callable[[Channels], Awaitable[Hashable]]:
        """The router as LangGraph calls it: channels in, the RunState handed over, sync or async alike."""

        async def route(channels: Channels) -> Hashable:
            decision = path(channels.run)
            return await decision if inspect.isawaitable(decision) else decision

        ### LangGraph names a branch after its callable: the user's router keeps its own name.
        route.__name__ = route.__qualname__ = getattr(path, "__name__", "route")
        return route

    def _topology_arcs(self) -> list[Arc]:
        """Every declared arc in a stable order: direct edges, join legs, then router branches."""
        direct = [(source, target, EdgeKind.DIRECT, "") for source, target in sorted(self.edges)]
        joins = [
            (source, target, EdgeKind.JOIN, "") for sources, target in sorted(self.waiting_edges) for source in sources
        ]
        branches = [
            (source, target, EdgeKind.CONDITIONAL, "" if str(key) == target else str(key))
            for source, specs in self.branches.items()
            for spec in specs.values()
            for key, target in (spec.ends or {}).items()
        ]
        return [*direct, *joins, *branches]

    def _sequence_one(self, node: NodeFunc | tuple[str, NodeFunc]) -> str:
        match node:
            case (str() as name, func):
                return self._add_one(name, cast("NodeFunc", func), {})
            case func:
                return self._add_one(func, None, {})

    def _common_instrumented(self) -> dict[str, InstrumentNode]:
        """The instrumented nodes in declaration order — LangGraph's internal handler nodes never count."""
        return {name: spec for name, spec in self.nodes.items() if isinstance(spec, InstrumentNode)}

    def _common_roles(self) -> dict[str, NodeRole]:
        """Each node's role, read off the arcs LangGraph's sentinels own: from START, into END, or neither."""
        arcs = self._topology_arcs()
        entered = {target for source, target, _, _ in arcs if source == START}
        leading = {source for source, target, _, _ in arcs if target == END}
        return {name: EDGE_ROLES[name in leading, name in entered] for name in self._common_instrumented()}

    @staticmethod
    def _topology_barycenter(dag: rx.PyDiGraph, placed: Mapping[int, float], index: int) -> tuple[float, int]:
        """Sort key of a vertex in its rank: the mean centred lane of its parents, the declaration breaking ties."""
        parents = dag.predecessor_indices(index)
        return (statistics.fmean(placed[parent] for parent in parents) if parents else 0.0, index)

    @classmethod
    def _topology_lanes(cls, dag: rx.PyDiGraph, generations: Sequence[Sequence[int]]) -> dict[int, tuple[int, int]]:
        """Rank and lane per vertex, rank after rank: a lane depends on the lanes already placed above it."""
        placed: dict[int, float] = {}
        grid: dict[int, tuple[int, int]] = {}
        for rank, generation in enumerate(generations):
            ordered = sorted(generation, key=lambda index: cls._topology_barycenter(dag, placed, index))
            placed |= {index: lane - (len(ordered) - 1) / 2 for lane, index in enumerate(ordered)}
            grid |= {index: (rank, lane) for lane, index in enumerate(ordered)}
        return grid

    def _stream_compiled(self) -> CompiledStateGraph[Channels, None, Channels, Channels]:
        match self._compiled:
            case None:
                msg = "InstrumentGraph not compiled: compile() once at startup, then stream or run"
                raise RuntimeError(msg)
            case compiled:
                return compiled

    @staticmethod
    def _stream_failure(error: Exception) -> str:
        """The verdict's error: a failed node's own message, or the type and message of anything else."""
        match error:
            case NodeError(output=output):
                return output.error
            case _:
                return f"{type(error).__name__}: {error}"

    def _stream_end(
        self, state: RunState, status: RunStatus, latency_ms: float, reached: set[str], error: str = ""
    ) -> RunEnd:
        skipped = tuple(name for name in self._common_instrumented() if name not in reached)
        end = RunEnd(run_id=state.id, status=status, latency_ms=latency_ms, skipped=skipped, error=error)
        logger.info(f"run {status}", run_id=state.id, latency_ms=latency_ms, skipped=skipped, error=error)
        return end

    ############################################################

    def add_node(  # ty: ignore[invalid-method-override] — the contract narrows LangGraph's open overloads on purpose
        self, node: str | NodeFunc, action: NodeFunc | None = None, **policies: Unpack[NodePolicies]
    ) -> Self:
        """Add an instrumented node: `add_node(node_extract)` or `add_node("name", node_extract)`."""
        self._add_one(node, action, policies)
        return self

    def add_sequence(  # ty: ignore[invalid-method-override] — same narrowing as add_node
        self, nodes: Sequence[NodeFunc | tuple[str, NodeFunc]]
    ) -> Self:
        """Add nodes chained in order, named as `add_node` names them."""
        names = [self._sequence_one(node) for node in nodes]
        for source, target in itertools.pairwise(names):
            self.add_edge(source, target)
        return self

    def add_conditional_edges(  # ty: ignore[invalid-method-override] — routers read the RunState, not raw channels
        self, source: str, path: Route, path_map: dict[Hashable, str] | Sequence[str] | None = None
    ) -> Self:
        """Route on the RunState; the router must name every target it can reach."""
        ends = self._route_ends(path, path_map)
        super().add_conditional_edges(source, self._route_wrap(path), ends)
        return self

    def compile(  # ty: ignore[invalid-method-override] — LangGraph's options pass through untouched
        self, **options: Any
    ) -> CompiledStateGraph[Channels, None, Channels, Channels]:
        """LangGraph's compile, after stamping every node with its role — the edges are final by now."""
        roles = self._common_roles()
        for name, node in self._common_instrumented().items():
            node.role = roles[name]
        self._compiled = super().compile(**options)
        return self._compiled

    @property
    def sections(self) -> frozenset[Section]:
        """The DARTS sections this graph mounts a node for — where its specs may run."""
        return frozenset(
            Section(node.category)
            for node in self._common_instrumented().values()
            if node.category in frozenset(Section)
        )

    def topology(self) -> Topology:
        """The declared graph as a placed map: O(V + E) for roles, loops and ranks, O(V log V) for lanes.

        The sentinels are not vertices — each node's role says where START and END are — so only arcs
        between nodes are drawn. The DFS starts from the entries: a loop's back edge is the one that
        points against the flow coming from START."""
        specs, roles = self._common_instrumented(), self._common_roles()
        arcs = [arc for arc in self._topology_arcs() if arc[0] in specs and arc[1] in specs]
        digraph: rx.PyDiGraph = rx.PyDiGraph(multigraph=True)
        index = dict(zip(specs, digraph.add_nodes_from(list(specs)), strict=True))
        digraph.add_edges_from_no_data([(index[source], index[target]) for source, target, _, _ in arcs])
        visitor = BackEdgeVisitor()
        entries_first = sorted(index.values(), key=lambda vertex: roles[digraph[vertex]] is not NodeRole.START)
        rx.digraph_dfs_search(digraph, entries_first, visitor)
        dag = digraph.copy()
        dag.remove_edges_from(list(visitor.found))
        grid = self._topology_lanes(dag, rx.topological_generations(dag))
        nodes = tuple(
            TopologyNode(
                id=name,
                role=roles[name],
                category=spec.category,
                summary=spec.doc,
                rank=grid[index[name]][0],
                lane=grid[index[name]][1],
            )
            for name, spec in specs.items()
        )
        edges = tuple(
            TopologyEdge(
                id=f"{source}>{target}:{kind}:{label}",
                source=source,
                target=target,
                kind=kind,
                label=label,
                loop=(index[source], index[target]) in visitor.found,
            )
            for source, target, kind, label in arcs
        )
        return Topology(
            nodes=nodes,
            edges=edges,
            ranks=1 + max((rank for rank, _ in grid.values()), default=-1),
            lanes=1 + max((lane for _, lane in grid.values()), default=-1),
        )

    async def stream(self, state: RunState, *, retain: bool = False) -> AsyncIterator[RunFrame]:
        """Run once: each NodeOutput as it is emitted, then the RunEnd — a failure is a verdict, not a raise.

        When the run closes — reaching END or failing, or abandoned by its consumer — its context is
        released from the store; the run span keeps a snapshot. `retain=True` keeps it (tests, debugging)."""
        compiled, reached, telemetry = self._stream_compiled(), set[str](), state.infra.telemetry
        logger.info("run started", run_id=state.id)
        try:
            with telemetry.run(state.id, state.context, state.correlation) as span, LatencyWrapper() as latency:
                try:
                    async for frame in compiled.astream(Channels(run=state), stream_mode="custom"):
                        match frame:
                            case NodeOutput(name=name):
                                reached.add(name)
                                yield frame
                            case _:
                                pass
                except Exception as error:  # noqa: BLE001 — the run's failure becomes its RunEnd, the node already logged it
                    end = self._stream_end(state, RunStatus.FAILED, latency.ms, reached, self._stream_failure(error))
                else:
                    end = self._stream_end(state, RunStatus.SUCCEEDED, latency.ms, reached)
                ### written while the run's span is open: it closes OK or ERROR, its context snapshotted before release.
                telemetry.verdict(span, end, state.context)
            yield end
        finally:
            match retain:
                case False:
                    state.release()
                case _:
                    pass

    async def run(self, state: RunState, *, retain: bool = False) -> RunResult:
        """The batch face of `stream`: the terminal outputs in order, and the RunEnd."""
        *frames, end = [frame async for frame in self.stream(state, retain=retain)]
        outputs = tuple(frame for frame in frames if isinstance(frame, NodeOutput) and frame.status in TERMINAL)
        ### `stream` closes on its RunEnd by construction: the last frame is the verdict.
        return RunResult(outputs=outputs, end=cast("RunEnd", end))
