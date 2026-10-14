"""tests/unit: instrument.graph — naming, routers, topology (ranks, lanes, loops, joins) and the run frames."""

from typing import TYPE_CHECKING, Any, Literal, cast

import pytest
from langgraph.config import get_stream_writer
from langgraph.graph import END, START
from opentelemetry.trace import StatusCode

from e_graph.instrument.errors import ContractError, ContractRule
from e_graph.instrument.graph import InstrumentGraph
from e_graph.instrument.models import EdgeKind, NodeOutput, NodeRole, NodeStatus, RunEnd, RunStatus
from e_graph.instrument.state import RunState
from e_graph.models.section import Section

if TYPE_CHECKING:
    from collections.abc import Callable

    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from core.state import State

    type Place = Callable[..., Any]


async def node_alpha(state: RunState) -> str:
    """Alpha headline."""
    state.context.trail = [*cast("list[str]", state.context.get("trail", [])), "alpha"]
    return "alpha said this"


async def node_beta(state: RunState) -> None:
    """Beta headline."""
    state.context.trail = [*cast("list[str]", state.context.get("trail", [])), "beta"]


async def node_gamma(state: RunState) -> None:
    """Gamma headline."""
    state.context.trail = [*cast("list[str]", state.context.get("trail", [])), "gamma"]


async def node_boom(state: RunState) -> None:
    """Always fails."""
    msg = "kaboom"
    raise ValueError(msg)


async def node_noisy(state: RunState) -> None:
    """Writes a foreign frame on the custom stream."""
    get_stream_writer()({"not": "a node output"})


def route_alpha(state: RunState) -> Literal["beta", "gamma"]:
    return "gamma" if state.context.get("go_gamma", False) else "beta"


async def route_async(state: RunState) -> str:
    return "beta"


def route_loose(state: RunState) -> str:
    return "beta"


def route_broken(state: RunState) -> Literal["beta"]:
    msg = "router lost its way"
    raise LookupError(msg)


@pytest.fixture
def chain(located: Place) -> InstrumentGraph:
    """START → alpha → beta → END, compiled."""
    graph = InstrumentGraph().add_sequence([located(node_alpha), located(node_beta)])
    graph.add_edge(START, "alpha").add_edge("beta", END).compile()
    return graph


##### NAMING #####
def test_add_node_derives_and_accepts_names(located: Place) -> None:
    graph = InstrumentGraph().add_node(located(node_alpha)).add_node("second", located(node_beta))
    assert list(graph.nodes) == ["alpha", "second"]


def test_a_pipeline_graph_mounts_its_own_nodes_one_per_section(located: Place) -> None:
    graph = InstrumentGraph(name="doc").add_node(located(node_alpha, "ingest")).add_node(located(node_beta, "probe"))
    assert graph.sections == {Section.INGEST}
    assert graph.nodes["alpha"].pipeline == "doc"  # ty: ignore[unresolved-attribute]


@pytest.mark.parametrize(
    ("second", "rule"),
    [(("extract", "filing"), ContractRule.PIPELINE), (("ingest", "doc"), ContractRule.SECTION)],
    ids=["foreign-pipeline", "section-taken"],
)
def test_a_pipeline_graph_refuses_what_is_not_its_own(
    located: Place, second: tuple[str, str], rule: ContractRule
) -> None:
    graph = InstrumentGraph(name="doc").add_node(located(node_alpha, "ingest"))
    with pytest.raises(ContractError) as caught:
        graph.add_node(located(node_beta, *second))
    assert (caught.value.rule, caught.value.subject) == (rule, "beta")


def test_add_node_rejects_bad_explicit_name(located: Place) -> None:
    with pytest.raises(ContractError) as caught:
        InstrumentGraph().add_node("Not-A-Name", located(node_alpha))
    assert caught.value.rule is ContractRule.NAME


def test_add_node_rejects_name_without_function() -> None:
    with pytest.raises(ContractError) as caught:
        InstrumentGraph().add_node("alpha")
    assert caught.value.rule is ContractRule.SIGNATURE


def test_add_sequence_names_and_chains(located: Place) -> None:
    graph = InstrumentGraph().add_sequence([located(node_alpha), ("second", located(node_beta))])
    assert list(graph.nodes) == ["alpha", "second"]
    assert ("alpha", "second") in graph.edges


##### ROUTERS #####
def test_router_ends_from_literal(located: Place) -> None:
    graph = InstrumentGraph().add_sequence([located(node_alpha)])
    graph.add_node(located(node_beta)).add_node(located(node_gamma))
    graph.add_conditional_edges("alpha", route_alpha)
    assert graph.branches["alpha"]["route_alpha"].ends == {"beta": "beta", "gamma": "gamma"}


def test_router_ends_from_path_map(located: Place) -> None:
    graph = InstrumentGraph().add_node(located(node_alpha)).add_node(located(node_beta))
    graph.add_conditional_edges("alpha", route_loose, ["beta"])
    graph.add_conditional_edges("alpha", route_async, {"go": "beta"})
    assert graph.branches["alpha"]["route_loose"].ends == {"beta": "beta"}
    assert graph.branches["alpha"]["route_async"].ends == {"go": "beta"}


def test_router_without_known_targets_refused(located: Place) -> None:
    graph = InstrumentGraph().add_node(located(node_alpha))
    with pytest.raises(ContractError) as caught:
        graph.add_conditional_edges("alpha", route_loose)
    assert caught.value.rule is ContractRule.ROUTE


@pytest.mark.parametrize(("go_gamma", "expected"), [(False, ["alpha", "beta"]), (True, ["alpha", "gamma"])])
async def test_router_reads_the_run_state(located: Place, system, go_gamma: bool, expected: list[str]) -> None:
    graph = InstrumentGraph().add_node(located(node_alpha)).add_node(located(node_beta)).add_node(located(node_gamma))
    graph.add_edge(START, "alpha").add_conditional_edges("alpha", route_alpha)
    graph.add_edge("beta", END).add_edge("gamma", END).compile()
    state = RunState(system)
    state.context.go_gamma = go_gamma
    await graph.run(state, retain=True)
    assert state.context.trail == expected


async def test_async_router_awaited(located: Place, system) -> None:
    graph = InstrumentGraph().add_node(located(node_alpha)).add_node(located(node_beta))
    graph.add_edge(START, "alpha").add_conditional_edges("alpha", route_async, ["beta"])
    graph.add_edge("beta", END).compile()
    state = RunState(system)
    await graph.run(state, retain=True)
    assert state.context.trail == ["alpha", "beta"]


##### TOPOLOGY #####
@pytest.fixture
def diamond(located: Place) -> InstrumentGraph:
    """START → alpha → (beta ∥ gamma) ⇒ boom, with a router from boom back to alpha or out."""
    graph = InstrumentGraph()
    for func in (node_alpha, node_beta, node_gamma, node_boom):
        graph.add_node(located(func))
    graph.add_edge(START, "alpha").add_edge("alpha", "beta").add_edge("alpha", "gamma")
    graph.add_edge(["beta", "gamma"], "boom")
    graph.add_conditional_edges("boom", route_loose, {"again": "alpha", "done": END})
    return graph


def test_topology_ranks_lanes_and_roles(diamond: InstrumentGraph) -> None:
    topology = diamond.topology()
    grid = {node.id: (node.rank, node.lane, node.role) for node in topology.nodes}
    assert grid == {
        "alpha": (0, 0, NodeRole.START),
        "beta": (1, 0, NodeRole.MID),
        "gamma": (1, 1, NodeRole.MID),
        "boom": (2, 0, NodeRole.END),
    }
    assert (topology.ranks, topology.lanes) == (3, 2)


def test_topology_edges_kinds_labels_loops(diamond: InstrumentGraph) -> None:
    edges = {(edge.source, edge.target): edge for edge in diamond.topology().edges}
    assert edges["beta", "boom"].kind is EdgeKind.JOIN
    assert edges["gamma", "boom"].kind is EdgeKind.JOIN
    assert edges["boom", "alpha"].kind is EdgeKind.CONDITIONAL
    assert edges["boom", "alpha"].label == "again"
    assert edges["boom", "alpha"].loop
    assert not edges["alpha", "beta"].loop
    assert edges["alpha", "beta"].kind is EdgeKind.DIRECT
    assert not {START, END} & {vertex for edge in edges for vertex in edge}


def test_topology_carries_category_and_headline(diamond: InstrumentGraph) -> None:
    alpha = next(node for node in diamond.topology().nodes if node.id == "alpha")
    assert (alpha.category, alpha.summary) == ("extract", "Alpha headline.")


def test_topology_lane_follows_parent_barycenter(located: Place) -> None:
    """gamma's child sits right of beta's child: the lanes follow the parents, never crossing."""
    graph = InstrumentGraph()
    for func in (node_alpha, node_beta, node_gamma, node_boom):
        graph.add_node(located(func))
    graph.add_node("tail", located(node_noisy))
    graph.add_edge(START, "alpha").add_edge("alpha", "beta").add_edge("alpha", "gamma")
    graph.add_edge("gamma", "boom").add_edge("beta", "tail")
    lanes = {node.id: node.lane for node in graph.topology().nodes}
    assert (lanes["beta"], lanes["gamma"]) == (0, 1)
    assert (lanes["tail"], lanes["boom"]) == (0, 1)


def test_topology_of_an_empty_graph() -> None:
    topology = InstrumentGraph().topology()
    assert (topology.nodes, topology.edges, topology.ranks, topology.lanes) == ((), (), 0, 0)


##### ROLES #####
def test_roles_stamped_at_compile(diamond: InstrumentGraph) -> None:
    assert {getattr(node, "role", None) for node in diamond.nodes.values()} == {NodeRole.MID}
    diamond.compile()
    roles = {name: getattr(node, "role", None) for name, node in diamond.nodes.items()}
    assert roles == {"alpha": NodeRole.START, "beta": NodeRole.MID, "gamma": NodeRole.MID, "boom": NodeRole.END}


def test_role_end_wins_a_lone_node(located: Place) -> None:
    """START → alpha → END: entered from START and leading to END — END, the output that closes the run."""
    graph = InstrumentGraph().add_node(located(node_alpha))
    graph.add_edge(START, "alpha").add_edge("alpha", END)
    assert graph.topology().nodes[0].role is NodeRole.END


async def test_outputs_carry_the_role(chain: InstrumentGraph, run_state: RunState) -> None:
    result = await chain.run(run_state)
    assert [(output.name, output.role) for output in result.outputs] == [
        ("alpha", NodeRole.START),
        ("beta", NodeRole.END),
    ]


##### RUN #####
async def test_stream_requires_compile(located: Place, run_state: RunState) -> None:
    graph = InstrumentGraph().add_node(located(node_alpha))
    with pytest.raises(RuntimeError, match="not compiled"):
        [frame async for frame in graph.stream(run_state)]


async def test_stream_frames_in_order(chain: InstrumentGraph, run_state: RunState) -> None:
    frames = [frame async for frame in chain.stream(run_state, retain=True)]
    assert [(getattr(frame, "name", "end"), frame.status) for frame in frames] == [
        ("alpha", NodeStatus.RUNNING),
        ("alpha", NodeStatus.SUCCEEDED),
        ("beta", NodeStatus.RUNNING),
        ("beta", NodeStatus.SUCCEEDED),
        ("end", RunStatus.SUCCEEDED),
    ]
    assert run_state.context.trail == ["alpha", "beta"]


async def test_summary_returned_beats_headline(chain: InstrumentGraph, run_state: RunState) -> None:
    result = await chain.run(run_state)
    assert [output.summary for output in result.outputs] == ["alpha said this", "Beta headline."]
    assert all(output.latency_ms > 0 for output in result.outputs)
    assert all(output.run_id == run_state.id for output in result.outputs)
    assert result.end == RunEnd(run_id=run_state.id, status=RunStatus.SUCCEEDED, latency_ms=result.end.latency_ms)


async def test_failure_becomes_the_verdict(located: Place, run_state: RunState) -> None:
    graph = InstrumentGraph().add_sequence([located(node_alpha), located(node_boom), located(node_beta)])
    graph.add_edge(START, "alpha").add_edge("beta", END).compile()
    result = await graph.run(run_state)
    failed = result.outputs[-1]
    assert (failed.name, failed.status, failed.error) == ("boom", NodeStatus.FAILED, "ValueError: kaboom")
    assert result.end.status is RunStatus.FAILED
    assert result.end.error == "ValueError: kaboom"
    assert result.end.skipped == ("beta",)


async def test_foreign_custom_frames_ignored(located: Place, run_state: RunState) -> None:
    graph = InstrumentGraph().add_node(located(node_noisy))
    graph.add_edge(START, "noisy").add_edge("noisy", END).compile()
    frames = [frame async for frame in graph.stream(run_state)]
    assert all(isinstance(frame, NodeOutput | RunEnd) for frame in frames)
    assert len(frames) == 3


async def test_spans_nest_under_the_run(located: Place, run_state: RunState, exporter: InMemorySpanExporter) -> None:
    graph = InstrumentGraph().add_sequence([located(node_alpha), located(node_boom)])
    graph.add_edge(START, "alpha").add_edge("boom", END).compile()
    result = await graph.run(run_state)
    spans = {span.name: span for span in exporter.get_finished_spans()}
    assert set(spans) == {"run", "node.alpha", "node.boom"}
    run_span = spans["run"].get_span_context()
    assert run_span is not None
    parents = [spans[name].parent for name in ("node.alpha", "node.boom")]
    assert all(parent is not None and parent.span_id == run_span.span_id for parent in parents)
    assert spans["node.boom"].status.status_code is StatusCode.ERROR
    assert result.outputs[0].trace_id == format(run_span.trace_id, "032x")
    assert dict(spans["node.alpha"].attributes or {})["node.category"] == "extract"


async def test_router_failure_is_the_verdict(located: Place, run_state: RunState) -> None:
    """A raise outside any node (here, a router) still ends as a verdict, named by its own type."""
    graph = InstrumentGraph().add_node(located(node_alpha)).add_node(located(node_beta))
    graph.add_edge(START, "alpha").add_conditional_edges("alpha", route_broken).add_edge("beta", END).compile()
    result = await graph.run(run_state)
    assert result.end.status is RunStatus.FAILED
    assert result.end.error == "LookupError: router lost its way"
    assert result.end.skipped == ("beta",)


async def test_spans_say_what_happened(located: Place, run_state: RunState, exporter: InMemorySpanExporter) -> None:
    """Over the real OTel adapter: a fine node closes OK with its summary, the failed run ERROR with its cause."""
    graph = InstrumentGraph().add_sequence([located(node_alpha), located(node_boom)])
    graph.add_edge(START, "alpha").add_edge("boom", END).compile()
    run_state.context.seed = "s1"
    await graph.run(run_state)
    spans = {span.name: span for span in exporter.get_finished_spans()}
    alpha, run = spans["node.alpha"], spans["run"]
    assert alpha.status.status_code is StatusCode.OK
    assert dict(alpha.attributes or {})["output.value"] == "alpha said this"
    assert spans["node.boom"].status.status_code is StatusCode.ERROR
    assert (run.status.status_code, run.status.description) == (StatusCode.ERROR, "ValueError: kaboom")
    assert '"seed":"s1"' in str(dict(run.attributes or {})["input.value"])


async def test_run_span_links_its_request(located: Place, system: State, exporter: InMemorySpanExporter) -> None:
    graph = InstrumentGraph().add_node(located(node_alpha))
    graph.add_edge(START, "alpha").add_edge("alpha", END).compile()
    await graph.run(RunState(system, correlation="req-7"))
    run = next(span for span in exporter.get_finished_spans() if span.name == "run")
    assert dict(run.attributes or {})["run.correlation_id"] == "req-7"
