"""logic.orchestrator.lab: a section seen before it runs — its map, its drawing, its rehearsal.

The map is the plan placed for drawing: every spec at its step (rank) and its place in the step (lane),
deterministic specs first, then each fused call's specs in call order, then the fallbacks held for the
step's specs; arcs for every dependency and every fallback; one group per planned fused call. It is built
from the very catalog and plan the orchestrator runs by, so the drawing is what runs.

    map ──▶ rustworkx PyDiGraph ──▶ to_dot() ──▶ graphviz (WebAssembly on wasmtime) ──▶ SVG

A rehearsal runs the pipeline up to the section, the section included — every earlier section in its
graph's rank order, once — on a copy of the system whose agent answers without a model: each spec from
its first example, or the least its schema accepts (strings matching their pattern). Runners run for
real, so every agent call the section issues is exactly what a live run would send: `Simulation.calls`.
`live=True` keeps the real agent."""

import atexit
import dataclasses
import random
import time
from functools import cache
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, ClassVar, Final

import anyio
import msgspec
import rstr
import rustworkx as rx
import wasi_graphviz

from e_graph.instrument.contexts import InstrumentContexts
from e_graph.instrument.state import RunState
from e_graph.logic.errors import EndpointError
from e_graph.logic.models import (
    CallGroup,
    LinkKind,
    Provider,
    Reply,
    Route,
    SectionInfo,
    SectionMap,
    SemanticSpec,
    Simulation,
    SpecLink,
    SpecPoint,
    Usage,
)
from e_graph.logic.orchestrator.fusion import SpecFusion
from e_graph.models.section import ORDER, Section
from infra.state import State

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from e_graph.instrument.graph import InstrumentGraph
    from e_graph.logic.models import Catalog, SectionPlan, Tier
    from e_graph.logic.orchestrator.core import OrchestratorCore
    from e_graph.logic.state import LogicState

MS_PER_SECOND: Final[float] = 1000.0
WALK: Final[tuple[Section, ...]] = (*ORDER, Section.CUSTOM)
### deterministic specs square, semantic ones rounded: the kind reads at a glance.
STYLES_KIND: Final[Mapping[str, str]] = MappingProxyType({"deterministic": "solid", "semantic": "rounded"})
STYLES: Final[Mapping[LinkKind, str]] = MappingProxyType({LinkKind.DEPENDS: "solid", LinkKind.FALLBACK: "dashed"})


@cache
def engine() -> None:
    """Once, on the first render: free the cached wasmtime engine at exit, while the interpreter still stands —
    torn down later, its finalizers run against modules already gone and print errors at every exit."""
    ### the package exposes no close of its own: its private cache is the one handle there is.
    atexit.register(wasi_graphviz._backends.clear)


class RehearsalAgent:
    """The agent a rehearsal talks to: every spec answered from its first example, or the least its schema accepts."""

    name: ClassVar[str] = "rehearsal"

    def __init__(self, examples: Mapping[str, Any], seed: int = 0) -> None:
        self._examples = examples
        ### seeded: the same schema rehearses to the same answer, run after run — no secret is ever drawn here.
        self._strings = rstr.Rstr(random.Random(seed))  # noqa: S311

    ##### PRIVATE #####

    def _run_least(self, schema: Mapping[str, Any]) -> Any:
        """The least value a JSON Schema accepts: its first enum or const, else the least of its first type."""
        match schema:
            case {"const": value}:
                return value
            case {"enum": [first, *_]}:
                return first
            case {"anyOf": [first, *_]} | {"oneOf": [first, *_]}:
                return self._run_least(first)
            case {"type": [first, *_]}:
                return self._run_least({**schema, "type": first})
            case {"type": str() as kind}:
                return self._run_typed()[kind](schema)
            case _:
                return {}

    def _run_typed(self) -> Mapping[str, Callable[[Mapping[str, Any]], Any]]:
        return {
            "object": lambda schema: {name: self._run_least(sub) for name, sub in schema.get("properties", {}).items()},
            "array": lambda schema: [self._run_least(schema.get("items", {}))] * schema.get("minItems", 0),
            "string": lambda schema: (
                self._strings.xeger(schema["pattern"]) if "pattern" in schema else "x" * schema.get("minLength", 0)
            ),
            "integer": lambda schema: schema.get("minimum", schema.get("exclusiveMinimum", -1) + 1),
            "number": lambda schema: float(schema.get("minimum", 0)),
            "boolean": lambda _: False,
            "null": lambda _: None,
        }

    ############################################################

    ##### PUBLIC #####

    async def run(self, *asked: Any, **_: Any) -> Reply[dict[str, Any]]:
        """Each spec of the fused schema (the third argument, as `AgnosticAgent.run` takes it) answered without a
        model; what it cost: nothing."""
        answer = {
            name: self._examples[name] if name in self._examples else self._run_least(schema)
            for name, schema in asked[2]["properties"].items()
        }
        return Reply(
            output=answer, provider=Provider.CUSTOM, model=self.name, usage=Usage(), latency_ms=0.0, attempts=1
        )


class SectionLab:
    """The orchestrator's sections, seen from outside: listed, mapped, drawn, rehearsed."""

    __slots__ = ("_graphs", "_orchestrator")

    def __init__(self, orchestrator: OrchestratorCore, graphs: Mapping[str, InstrumentGraph]) -> None:
        self._orchestrator, self._graphs = orchestrator, graphs

    ##### PRIVATE — the map #####

    @staticmethod
    def _map_lanes(plan: SectionPlan) -> dict[str, tuple[int, int]]:
        """Each spec's (rank, lane): a step's deterministic specs, its fused specs in call order, then its fallbacks."""
        rows = [
            [*step.specs, *sorted(plan.fallbacks[name] for name in step.specs if name in plan.fallbacks)]
            for step in plan.steps
        ]
        return {name: (rank, lane) for rank, row in enumerate(rows) for lane, name in enumerate(row)}

    @staticmethod
    def _map_groups(catalog: Catalog, plan: SectionPlan) -> tuple[CallGroup, ...]:
        """Every planned fused call, numbered in plan order, weighed as the plan weighed it."""
        planned = [(step.index, call) for step in plan.steps for call in step.fused]
        nodes, wiki = catalog.nodes, catalog.wiki
        return tuple(
            CallGroup(
                index=index,
                rank=rank,
                tier=call.tier,
                specs=call.specs,
                weight=sum(SpecFusion.weight(nodes[name], wiki) for name in call.specs),
                budget=0,
            )
            for index, (rank, call) in enumerate(planned)
        )

    def _map_build(self, catalog: Catalog, plan: SectionPlan) -> SectionMap:
        places = self._map_lanes(plan)
        groups = self._map_groups(catalog, plan)
        budget = self._orchestrator.conf.fusion_tokens
        calls = {name: group.index for group in groups for name in group.specs}
        rescues = {fallback: parent for parent, fallback in plan.fallbacks.items()}
        nodes = tuple(
            SpecPoint(
                id=name,
                kind=str(node.spec.__struct_config__.tag),
                description=node.spec.description,
                rank=places[name][0],
                lane=places[name][1],
                tier=str(node.spec.tier) if isinstance(node.spec, SemanticSpec) else "",
                call=calls.get(name, -1),
                rescues=rescues.get(name, ""),
                runners=dict(node.spec.plugs),
                wiki=node.spec.wiki,
                output=dict(node.spec.output),
            )
            for name, node in sorted(catalog.nodes.items(), key=lambda item: places[item[0]])
        )
        edges = (
            *(
                SpecLink(id=f"{dependency}->{name}", source=dependency, target=name, kind=LinkKind.DEPENDS)
                for name, node in sorted(catalog.nodes.items())
                for dependency in node.spec.depends
            ),
            *(
                SpecLink(id=f"{parent}~>{fallback}", source=parent, target=fallback, kind=LinkKind.FALLBACK)
                for parent, fallback in sorted(plan.fallbacks.items())
            ),
        )
        return SectionMap(
            pipeline=catalog.pipeline,
            section=catalog.section,
            nodes=nodes,
            edges=edges,
            calls=tuple(msgspec.structs.replace(group, budget=budget) for group in groups),
            ranks=len(plan.steps),
            lanes=max((lane + 1 for _, lane in places.values()), default=0),
        )

    ##### PRIVATE — the drawing #####

    @staticmethod
    def _dot_graph(mapped: SectionMap) -> tuple[rx.PyDiGraph[SpecPoint, SpecLink], dict[str, int]]:
        """The map as a rustworkx graph: specs as nodes, arcs as edges."""
        graph: rx.PyDiGraph[SpecPoint, SpecLink] = rx.PyDiGraph()
        index = {point.id: graph.add_node(point) for point in mapped.nodes}
        graph.add_edges_from([(index[link.source], index[link.target], link) for link in mapped.edges])
        return graph, index

    @staticmethod
    def _dot_node(point: SpecPoint) -> dict[str, str]:
        runners = "\\n".join(f"{slot}: {ref}" for slot, ref in point.runners.items())
        tier = f" · {point.tier}" if point.tier else ""
        return {
            "label": f"{point.id}\\n{point.kind}{tier}\\n{runners}",
            "shape": "box",
            "style": STYLES_KIND[point.kind],
            "fontname": "monospace",
            "fontsize": "10",
        }

    @staticmethod
    def _dot_edge(link: SpecLink) -> dict[str, str]:
        return {"style": STYLES[link.kind]}

    ############################################################

    ##### PUBLIC #####

    async def sections(self) -> tuple[SectionInfo, ...]:
        """Every mounted section of every pipeline, in walking order, with what its plan holds."""
        plans = [
            await self._orchestrator.plan(pipeline, section)
            for pipeline, graph in sorted(self._graphs.items())
            for section in WALK
            if section in graph.sections
        ]
        return tuple(
            SectionInfo(
                pipeline=plan.pipeline,
                section=plan.section,
                specs=sum(len(step.specs) for step in plan.steps) + len(plan.fallbacks),
                steps=len(plan.steps),
                calls=sum(len(step.fused) for step in plan.steps),
            )
            for plan in plans
        )

    async def map(self, pipeline: str, section: Section) -> SectionMap:
        """The section placed for drawing, from the very catalog and plan it runs by."""
        catalog = await self._orchestrator.catalog(pipeline, section)
        return self._map_build(catalog, await self._orchestrator.plan(pipeline, section))

    def dot(self, mapped: SectionMap) -> str:
        """The map in DOT, from rustworkx: steps top to bottom, each planned fused call a dashed cluster."""
        graph, index = self._dot_graph(mapped)
        title = f'"{mapped.pipeline} · {mapped.section}"'
        dot = graph.to_dot(
            node_attr=self._dot_node,
            edge_attr=self._dot_edge,
            graph_attr={"rankdir": "TB", "label": title, "labelloc": "t", "fontname": "monospace"},
        )
        clusters = "".join(
            f'subgraph cluster_{group.index} {{ label="call-{group.index} · {group.tier} · ~{group.weight}/{group.budget}"; '
            f'style=dashed; fontname="monospace"; fontsize=9; {" ".join(str(index[name]) for name in group.specs)}; }}\n'
            for group in mapped.calls
        )
        return f"{dot.rstrip().removesuffix('}')}{clusters}}}\n"

    @staticmethod
    def pipeline_dot(graph: InstrumentGraph) -> str:
        """A pipeline's LangGraph graph in DOT, from rustworkx: its nodes by section, its arcs by kind, loops dashed."""
        topology = graph.topology()
        drawn: rx.PyDiGraph[str, str] = rx.PyDiGraph()
        index = {
            node.id: drawn.add_node(node.id if node.category == node.id else f"{node.id}\\n{node.category}")
            for node in topology.nodes
        }
        drawn.add_edges_from(
            [(index[edge.source], index[edge.target], "dashed" if edge.loop else "solid") for edge in topology.edges]
        )
        return drawn.to_dot(
            node_attr=lambda label: {"label": label, "shape": "box", "style": "rounded", "fontname": "monospace"},
            edge_attr=lambda style: {"style": style},
            graph_attr={"rankdir": "TB", "label": f'"{graph.name}"', "labelloc": "t", "fontname": "monospace"},
        )

    @staticmethod
    def svg(dot: str) -> str:
        """DOT rendered by Graphviz compiled to WebAssembly, on wasmtime: no native binary needed."""
        engine()
        return wasi_graphviz.render(dot, format="svg", backend="wasmtime").decode()

    async def simulate(
        self, pipeline: str, section: Section, data: Mapping[str, Any], *, system: State, live: bool = False
    ) -> Simulation:
        """The pipeline run up to `section`, the section included, on a copy of the system — rehearsed or live."""
        started = time.perf_counter()
        ### earlier sections in the graph's rank order, each once: a loop back is no rehearsal's business.
        ranks = {node.category: node.rank for node in self._graphs[pipeline].topology().nodes if node.category in WALK}
        earlier = sorted((rank, Section(name)) for name, rank in ranks.items() if rank < ranks[section])
        sections = [*(name for _, name in earlier), section]
        catalogs = [await self._orchestrator.catalog(pipeline, name) for name in sections]
        examples = {
            name: node.spec.examples[0]
            for catalog in catalogs
            for name, node in catalog.nodes.items()
            if isinstance(node.spec, SemanticSpec) and node.spec.examples
        }
        agent = system.logic.agent if live else RehearsalAgent(examples)
        ### the system's root, as RunState takes it: a copy of the whole tree, the agent swapped, its own contexts.
        sandbox = State(
            infra=system.infra,
            logic=dataclasses.replace(system.logic, agent=agent),
            instrument=dataclasses.replace(system.instrument, contexts=InstrumentContexts()),
        )
        sandbox.seal()
        state = RunState(sandbox, pipeline=pipeline)
        state.context.update(data)
        try:
            runs = [await self._orchestrator.run(name, state) for name in sections]
            written = self.plain(getattr(state.context, section))
        finally:
            state.release()
        calls = runs[-1].calls
        tiers = sorted({call.tier for call in calls})
        return Simulation(
            pipeline=pipeline,
            section=section,
            live=live,
            runs=tuple(runs),
            calls=calls,
            routes={str(tier): self.route(system.logic, tier) for tier in tiers},
            written=written,
            latency_ms=(time.perf_counter() - started) * MS_PER_SECOND,
        )

    @staticmethod
    def route(logic: LogicState, tier: Tier) -> Route:
        """Where a tier's calls go — provider, model, base; the key never leaves the agent."""
        try:
            endpoint = logic.agent.resolve(tier)
        except EndpointError as missing:
            return Route(error=str(missing))
        return Route(provider=str(endpoint.provider), model=endpoint.model, api_base=endpoint.api_base)

    @staticmethod
    def plain(data: Any) -> dict[str, Any]:
        """A context node as plain JSON-able builtins, nested States included."""
        return msgspec.to_builtins(dict(data), enc_hook=dict, order="sorted")

    @staticmethod
    async def render(dot: str) -> str:
        """`svg` off the loop: the first render compiles the module (~150 ms), the next ones take ~2 ms."""
        return await anyio.to_thread.run_sync(SectionLab.svg, dot)
