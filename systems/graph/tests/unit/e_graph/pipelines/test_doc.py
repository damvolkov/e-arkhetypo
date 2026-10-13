"""tests/unit: pipelines.doc — the demo builder end to end: its declaration, then one run per `resources/cases` case."""

from typing import TYPE_CHECKING, Any, cast

import eserde
import pytest

from e_graph.instrument.models import NodeRole, NodeStatus, RunStatus
from e_graph.instrument.state import RunState
from e_graph.models.section import ORDER, Section
from e_graph.pipelines.doc import DocBuilder

if TYPE_CHECKING:
    from pytest_resources import Resources

    from core.state import State
    from e_graph.instrument.graph import InstrumentGraph

ALL: tuple[str, ...] = ("ingest", "normalize", "classify", "extract", "validate", "transform", "report")


@pytest.fixture
def pipeline() -> InstrumentGraph:
    return DocBuilder().build()


def test_builder_names_and_summarizes_its_graph(pipeline: InstrumentGraph) -> None:
    assert (pipeline.name, pipeline.summary) == ("doc", DocBuilder().summary)
    assert pipeline.summary.startswith("Document intake")


def test_every_node_is_a_section(pipeline: InstrumentGraph) -> None:
    categories = {node.id: node.category for node in pipeline.topology().nodes if node.category}
    assert categories == {name: Section(name) for name in ALL}
    assert [section for section in ORDER if section in categories.values()] == list(ALL)


def test_roles_entry_and_exit(pipeline: InstrumentGraph) -> None:
    roles = {node.id: node.role for node in pipeline.topology().nodes}
    assert (roles["ingest"], roles["report"]) == (NodeRole.START, NodeRole.END)
    assert {role for name, role in roles.items() if name not in {"ingest", "report"}} == {NodeRole.MID}


def test_shape_parallel_pair_and_loop(pipeline: InstrumentGraph) -> None:
    topology = pipeline.topology()
    ranks = {node.id: node.rank for node in topology.nodes}
    assert ranks["normalize"] == ranks["classify"]
    assert [edge.target for edge in topology.edges if edge.loop] == ["extract"]


async def test_documents_meet_their_expectations(
    pipeline: InstrumentGraph, system: State, resources: Resources
) -> None:
    """Every case under resources/documents: seeded data in, the expected verdict and values out."""
    cases = cast("list[dict[str, Any]]", list(resources.cases))
    assert len(cases) >= 4
    for case in cases:
        state = RunState(system)
        state.context.update(case["data"])
        result = await pipeline.run(state, retain=True)
        expect = case["expect"]
        assert (case["name"], result.end.status) == (case["name"], RunStatus(expect["status"]))
        assert (state.context.kind, state.context.amount) == (expect["kind"], expect["amount"])
        assert result.outputs[-1].status is NodeStatus(expect["status"])
        match expect:
            case {"failed_at": failed_at}:
                assert result.outputs[-1].name == failed_at
            case {"report": report}:
                assert eserde.loads(state.context.report, format=case["data"]["format"])["kind"] == "invoice"
                assert cast("bytes", state.context.report).decode().startswith(report)
            case {"extractions": extractions}:
                assert [output.name for output in result.outputs].count("extract") == extractions


async def test_injected_failure_skips_the_tail(pipeline: InstrumentGraph, system: State) -> None:
    state = RunState(system)
    state.context.fail = True
    result = await pipeline.run(state)
    assert result.end.status is RunStatus.FAILED
    assert result.end.error == "RuntimeError: extraction failed on purpose"
    assert result.end.skipped == ("validate", "transform", "report")
