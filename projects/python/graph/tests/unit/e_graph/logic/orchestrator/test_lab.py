"""tests/unit: logic.orchestrator.lab — the section's map as drawn, its DOT and SVG, the rehearsal and its payloads."""

import re
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import TYPE_CHECKING, Any, Final

import pytest

from e_graph.instrument.contexts import InstrumentContexts
from e_graph.instrument.state import InfraState, InstrumentState, ProcessorsState
from e_graph.instrument.telemetry import InstrumentTelemetry
from e_graph.logic.agent import AgnosticAgent
from e_graph.logic.models import CallGroup, LinkKind, Route, SpecLink, Tier
from e_graph.logic.orchestrator.core import OrchestratorCore
from e_graph.logic.orchestrator.lab import RehearsalAgent, SectionLab
from e_graph.logic.state import LogicState
from e_graph.models.section import Section
from e_graph.pipelines.base import PipelineRegistry
from infra.state import State
from processors.doc import DocProcessor
from support.darts import SECTION, ScriptedAgent
from support.docling import GoldenPort

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from e_graph.instrument.graph import InstrumentGraph
    from providers.adapters.liteparse import LiteparseAdapter
    from support.darts import DartsHarness

AAPL: Final[str] = str(Path(__file__).resolve().parents[5] / "tests/resources/documents/filings/aapl-10k-2025.pdf")


@pytest.fixture
async def graphs() -> Mapping[str, InstrumentGraph]:
    return await PipelineRegistry().build()


def tree(graphs: Mapping[str, InstrumentGraph], agent: Any, pages: LiteparseAdapter) -> State:
    """The sealed system a rehearsal copies, branch for branch as the lifespans mount it: the real processor over replayed docling spans, the agent given."""
    root = State(
        infra=InfraState(
            providers=None,  # ty: ignore[invalid-argument-type]
            engines=None,  # ty: ignore[invalid-argument-type]
            processors=ProcessorsState(doc=DocProcessor(GoldenPort(), pages)),
            graphs=MappingProxyType(dict(graphs)),
        ),
        logic=LogicState(agent=agent, orchestrator=OrchestratorCore()),
        instrument=InstrumentState(telemetry=InstrumentTelemetry(), contexts=InstrumentContexts()),
    )
    root.seal()
    return root


##### THE MAP #####
async def test_the_diagram_is_placed_as_it_runs(darts: DartsHarness) -> None:
    darts.diagram()
    mapped = await SectionLab(darts.orchestrator, {}).map("doc", SECTION)
    places = {point.id: (point.rank, point.lane) for point in mapped.nodes}
    assert places == {
        "EXT-lines": (0, 0),
        "EXT-meta": (0, 1),
        "EXT-kind": (0, 2),
        "EXT-party": (0, 3),
        "EXT-currency": (1, 0),
        "EXT-total": (1, 1),
        "EXT-audit": (2, 0),
        "EXT-recount": (2, 1),
    }
    assert (mapped.ranks, mapped.lanes) == (3, 4)
    points = {point.id: point for point in mapped.nodes}
    assert (points["EXT-recount"].rescues, points["EXT-kind"].call, points["EXT-lines"].call) == ("EXT-audit", 0, -1)
    assert (points["EXT-kind"].tier, points["EXT-lines"].runners) == ("medium", {"runner": "owned/lines"})
    assert [(group.index, group.rank, group.specs, group.budget) for group in mapped.calls] == [
        (0, 0, ("EXT-kind", "EXT-party"), 8000),
        (1, 1, ("EXT-currency", "EXT-total"), 8000),
    ]
    assert all(isinstance(group, CallGroup) and group.weight > 0 for group in mapped.calls)
    assert SpecLink(id="EXT-audit~>EXT-recount", source="EXT-audit", target="EXT-recount", kind=LinkKind.FALLBACK) in (
        mapped.edges
    )
    assert {(link.source, link.target) for link in mapped.edges if link.kind is LinkKind.DEPENDS} == {
        ("EXT-lines", "EXT-total"),
        ("EXT-meta", "EXT-total"),
        ("EXT-kind", "EXT-total"),
        ("EXT-party", "EXT-currency"),
        ("EXT-total", "EXT-audit"),
        ("EXT-currency", "EXT-audit"),
    }


async def test_the_drawing_is_rustworkx_dot_rendered_to_svg(darts: DartsHarness) -> None:
    darts.diagram()
    lab = SectionLab(darts.orchestrator, {})
    dot = lab.dot(await lab.map("doc", SECTION))
    assert dot.startswith("digraph {")
    assert dot.rstrip().endswith("}")
    assert len(re.findall(r"subgraph cluster_\d", dot)) == 2
    assert 'label="call-0 · medium · ~' in dot
    assert "style=dashed" in dot
    assert "EXT-recount\\ndeterministic\\nrunner: owned/recount" in dot
    svg = await lab.render(dot)
    assert "<svg" in svg
    assert "call&#45;1" in svg


async def test_a_pipeline_draws_as_its_graph(graphs: Mapping[str, InstrumentGraph]) -> None:
    dot = SectionLab.pipeline_dot(graphs["doc"])
    assert dot.count("->") == len(graphs["doc"].topology().edges)
    assert 'label="doc"' in dot
    assert "style=dashed" in dot
    assert "<svg" in SectionLab.svg(dot)


async def test_sections_list_what_every_pipeline_mounts(graphs: Mapping[str, InstrumentGraph]) -> None:
    sections = await SectionLab(OrchestratorCore(), graphs).sections()
    assert [(info.pipeline, info.section) for info in sections if info.pipeline == "filing"] == [
        ("filing", Section.INGEST),
        ("filing", Section.EXTRACT),
        ("filing", Section.AUDIT),
        ("filing", Section.REPORT),
    ]
    extract = next(info for info in sections if (info.pipeline, info.section) == ("filing", Section.EXTRACT))
    assert (extract.specs, extract.steps, extract.calls) == (3, 1, 1)


async def test_an_empty_mounted_section_lists_as_empty(darts: DartsHarness) -> None:
    graph = SimpleNamespace(sections=frozenset({Section.EXTRACT}))
    (info,) = await SectionLab(darts.orchestrator, {"doc": graph}).sections()  # ty: ignore[invalid-argument-type]
    assert (info.specs, info.steps, info.calls) == (0, 0, 0)


##### THE REHEARSAL #####
async def test_a_rehearsal_runs_every_earlier_section_once(
    graphs: Mapping[str, InstrumentGraph], pages: LiteparseAdapter
) -> None:
    system = tree(graphs, ScriptedAgent(), pages)
    lab = SectionLab(system.logic.orchestrator, graphs)
    data = {"document": "invoice 3 total 7.25"}
    simulation = await lab.simulate("doc", Section.VALIDATE, data, system=system)
    assert [run.section for run in simulation.runs] == ["ingest", "classify", "normalize", "extract", "validate"]
    assert (simulation.written, simulation.calls, simulation.routes, simulation.live) == (
        {"VAL-amount": {"valid": True}},
        (),
        {},
        False,
    )
    assert simulation.latency_ms > 0


async def test_a_rehearsal_sends_what_a_live_run_sends_and_answers_without_a_model(
    graphs: Mapping[str, InstrumentGraph], pages: LiteparseAdapter
) -> None:
    agent = ScriptedAgent()
    system = tree(graphs, agent, pages)
    simulation = await SectionLab(system.logic.orchestrator, graphs).simulate(
        "filing", Section.EXTRACT, {"source": AAPL}, system=system
    )
    (call,) = simulation.calls
    assert (call.specs, call.tier, agent.calls) == (("EXT-balance", "EXT-cover", "EXT-income"), Tier.MEDIUM, [])
    assert "### Material for EXT-income\n## Page 43" in call.prompt
    assert "416,161" in call.prompt
    assert "data:image" not in call.prompt
    assert set(call.weights) == set(call.specs)
    assert simulation.routes == {
        "medium": Route(provider="vllm", model="scripted-medium", api_base="http://scripted/v1")
    }
    cover = simulation.written["EXT-cover"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", cover["period_end"])
    assert (cover["shares_outstanding"], simulation.written["EXT-income"]["revenue"]) == (1, 0)


async def test_a_live_rehearsal_asks_the_real_agent(
    graphs: Mapping[str, InstrumentGraph], pages: LiteparseAdapter
) -> None:
    agent = ScriptedAgent()
    agent.answers["EXT-cover"] = {"company": "Apple Inc.", "period_end": "2025-09-27", "shares_outstanding": 7}
    system = tree(graphs, agent, pages)
    simulation = await SectionLab(system.logic.orchestrator, graphs).simulate(
        "filing", Section.EXTRACT, {"source": AAPL}, system=system, live=True
    )
    assert (simulation.live, len(agent.calls)) == (True, 1)
    assert simulation.written["EXT-cover"]["company"] == "Apple Inc."


async def test_examples_answer_first(
    darts: DartsHarness, graphs: Mapping[str, InstrumentGraph], pages: LiteparseAdapter
) -> None:
    total = {"type": "object", "properties": {"total": {"type": "number"}}}
    darts.semantic("EXT-a", output=total, examples=({"total": 9.5},))
    darts.semantic("EXT-b", output=total)
    graph = graphs["doc"]
    system = tree({"doc": graph}, ScriptedAgent(), pages)
    lab = SectionLab(darts.orchestrator, {"doc": graph})
    simulation = await lab.simulate("doc", Section.INGEST, {}, system=system)
    assert simulation.runs[-1].section == Section.INGEST
    rehearsed = await lab.simulate("doc", SECTION, {}, system=system)
    assert rehearsed.written == {"EXT-a": {"total": 9.5}, "EXT-b": {"total": 0.0}}


async def test_a_tier_without_endpoint_routes_to_its_reason(
    settings: Callable[..., Any], pages: LiteparseAdapter
) -> None:
    async with AgnosticAgent(settings()) as agent:
        route = SectionLab.route(tree({}, agent, pages).logic, Tier.HIGH)
    assert route.error.startswith("tier high has no endpoint")


@pytest.mark.parametrize(
    ("schema", "least"),
    [
        ({"const": "x"}, "x"),
        ({"enum": ["EUR", "USD"]}, "EUR"),
        ({"anyOf": [{"type": "integer"}, {"type": "string"}]}, 0),
        ({"oneOf": [{"type": "boolean"}]}, False),
        ({"type": ["null", "string"]}, None),
        ({"type": "string", "minLength": 3}, "xxx"),
        ({"type": "integer", "minimum": 4}, 4),
        ({"type": "integer", "exclusiveMinimum": 4}, 5),
        ({"type": "number", "minimum": 2}, 2.0),
        ({"type": "array", "items": {"type": "integer"}, "minItems": 2}, [0, 0]),
        ({"type": "object", "properties": {"a": {"type": "boolean"}}}, {"a": False}),
        ({}, {}),
    ],
)
def test_the_least_a_schema_accepts(schema: dict[str, Any], least: Any) -> None:
    assert RehearsalAgent({})._run_least(schema) == least


def test_a_pattern_rehearses_to_a_match_the_same_every_time() -> None:
    schema = {"type": "string", "pattern": "^[A-Z]{3}-\\d{2}$"}
    first, second = RehearsalAgent({})._run_least(schema), RehearsalAgent({})._run_least(schema)
    assert first == second
    assert re.fullmatch("[A-Z]{3}-\\d{2}", first)


##### THE NOTE'S MAP #####
async def test_the_note_extract_map_is_placed_as_the_plan_ranks_it(graphs: Mapping[str, InstrumentGraph]) -> None:
    mapped = await SectionLab(OrchestratorCore(), graphs).map("note", Section.EXTRACT)
    assert (mapped.pipeline, mapped.section, mapped.ranks) == ("note", Section.EXTRACT, 3)
    places = {point.id: (point.rank, point.lane) for point in mapped.nodes}
    assert (
        places["EXT-amounts"],
        places["EXT-schedule-table"],
        places["EXT-payoff"],
        places["EXT-terms"],
    ) == ((0, 0), (0, 4), (0, 5), (2, 0))
    assert places["EXT-underlier"] == (0, 14)
    assert places["EXT-listing"] == (0, 15)
    assert places["EXT-identifiers-read"] == (0, 18)
    assert places["EXT-coupon-schedule"] == (1, 1)
    assert mapped.lanes == 19
    tiers = [(group.rank, str(group.tier), len(group.specs)) for group in mapped.calls]
    assert tiers == [(0, "high", 1), (0, "medium", 8), (0, "medium", 1), (0, "low", 3), (1, "low", 1)]
    assert all(group.budget == 8000 for group in mapped.calls)
    assert (
        SpecLink(
            id="EXT-identifiers~>EXT-identifiers-read",
            source="EXT-identifiers",
            target="EXT-identifiers-read",
            kind=LinkKind.FALLBACK,
        )
        in mapped.edges
    )


async def test_the_note_extract_drawing_holds_every_spec_and_the_fallback_style(
    graphs: Mapping[str, InstrumentGraph],
) -> None:
    lab = SectionLab(OrchestratorCore(), graphs)
    dot = lab.dot(await lab.map("note", Section.EXTRACT))
    assert 'label="note · extract"' in dot
    assert all(f'label="{name}' in dot for name in ("EXT-payoff", "EXT-terms", "EXT-identifiers-read"))
    assert "call-1 · medium" in dot
    assert "call-4 · low" in dot
    assert "style=dashed" in dot
