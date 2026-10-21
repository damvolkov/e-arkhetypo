"""tests/unit: pipelines.filing.graph — a 10-K read into its facts, the agent scripted, docling replayed from its spans.

The ingest is real (liteparse in-process, docling's recorded spans); the agent answers each spec as the
statements print it, in millions — so what is tested is everything around the model: the pages each spec
is fed, the one fused call, the scaling to dollars, the audits, the record — held to the XBRL truth."""

import re
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

import pytest

from core.state import State
from e_graph.instrument.models import RunStatus
from e_graph.instrument.state import ContextState, InfraState, ProcessorsState, RunState
from e_graph.instrument.telemetry import InstrumentTelemetry
from e_graph.logic.orchestrator.core import OrchestratorCore
from e_graph.pipelines.filing.graph import FilingGraph
from processors.doc import DocProcessor
from support.darts import ScriptedAgent
from support.docling import GoldenPort

if TYPE_CHECKING:
    from pytest_resources import Resources

    from e_graph.instrument.graph import InstrumentGraph

FILINGS: Final[Path] = Path(__file__).resolve().parents[5] / "tests" / "resources" / "documents" / "filings"
MILLION: Final[int] = 1_000_000
### what Apple's statements print for fiscal 2025, in millions — the scripted model reads it right.
COVER: Final[dict[str, Any]] = {"company": "Apple Inc.", "period_end": "2025-09-27", "shares_outstanding": 14776353000}
INCOME: Final[dict[str, Any]] = {
    "revenue": 416161,
    "cost_of_revenue": 220960,
    "gross_profit": 195201,
    "operating_income": 133050,
    "net_income": 112010,
    "eps_basic": 7.49,
    "eps_diluted": 7.46,
}
BALANCE: Final[dict[str, Any]] = {"total_assets": 359241, "total_liabilities": 285508, "equity": 73733, "cash": 35934}


@pytest.fixture
def agent() -> ScriptedAgent:
    scripted = ScriptedAgent()
    scripted.answers.update({"EXT-cover": COVER, "EXT-income": INCOME, "EXT-balance": BALANCE})
    return scripted


@pytest.fixture
def state(agent: ScriptedAgent) -> RunState:
    """A run over Apple's 10-K: the real processor on replayed docling spans, the scripted agent."""
    infra = InfraState(
        adapters=None,  # ty: ignore[invalid-argument-type]
        processors=ProcessorsState(doc=DocProcessor(GoldenPort())),
        agent=agent,  # ty: ignore[invalid-argument-type]
        orchestrator=OrchestratorCore(),
        telemetry=InstrumentTelemetry(),
        graphs=MappingProxyType({}),
    )
    system = State(infra=infra, contexts=ContextState())
    system.seal()
    run = RunState(system, pipeline="filing")
    run.context.source = str(FILINGS / "aapl-10k-2025.pdf")
    return run


@pytest.fixture
def pipeline() -> InstrumentGraph:
    return FilingGraph().build()


def test_the_graph_is_a_line_of_four_sections(pipeline: InstrumentGraph) -> None:
    assert [node.id for node in pipeline.topology().nodes] == ["ingest", "extract", "audit", "report"]
    assert pipeline.summary == "A 10-K read into its facts: ingest → extract → audit → report."


async def test_a_10k_reads_into_its_xbrl_facts(
    pipeline: InstrumentGraph, state: RunState, agent: ScriptedAgent, resources: Resources
) -> None:
    result = await pipeline.run(state, retain=True)
    assert result.end.status is RunStatus.SUCCEEDED, result.end.error
    truth = next(
        entry for entry in resources.documents["corpus"]["documents"] if entry["file"].startswith("filings/aapl")
    )
    record = dict(state.context.report["REP-facts"])
    facts = {name: fact["value"] for name, fact in truth["truth"]["facts"].items() if name in record["facts"]}
    assert len(facts) == len(INCOME) + len(BALANCE)
    assert (record["company"], record["period_end"], record["facts"], record["broken"]) == (
        truth["truth"]["company"],
        truth["truth"]["period_end"],
        facts,
        [],
    )
    assert record["shares_outstanding"] == truth["truth"]["shares_outstanding"]["value"]


async def test_one_fused_call_reads_only_the_pages_each_spec_points_to(
    pipeline: InstrumentGraph, state: RunState, agent: ScriptedAgent
) -> None:
    await pipeline.run(state, retain=True)
    (call,) = agent.calls
    assert call["specs"] == ("EXT-balance", "EXT-cover", "EXT-income")
    prompt = call["prompt"]
    ### each spec fed its own pages, in page order: the cover's leading three, each statement's best three.
    assert re.findall(r"### Material for [A-Za-z-]+|## Page \d+", prompt) == [
        "### Material for EXT-cover", "## Page 1", "## Page 2", "## Page 3",
        "### Material for EXT-income", "## Page 43", "## Page 44", "## Page 78",
        "### Material for EXT-balance", "## Page 46", "## Page 53", "## Page 72",
    ]  # fmt: skip
    assert "Glossary, statement-units" in call["instructions"]
    assert "416,161" in prompt


async def test_figures_that_break_the_balance_are_flagged_not_hidden(
    pipeline: InstrumentGraph, state: RunState, agent: ScriptedAgent
) -> None:
    agent.answers["EXT-balance"] = {**BALANCE, "equity": 2106}
    result = await pipeline.run(state, retain=True)
    assert result.end.status is RunStatus.SUCCEEDED
    audit = state.context.audit
    assert (audit["AUD-balance"]["holds"], audit["AUD-margin"]["holds"]) == (False, True)
    assert audit["AUD-balance"]["gap"] == (BALANCE["equity"] - 2106) * MILLION
    assert state.context.report["REP-facts"]["broken"] == ["AUD-balance"]


async def test_a_model_down_stops_the_run_at_extract(
    pipeline: InstrumentGraph, state: RunState, agent: ScriptedAgent
) -> None:
    agent.down.add("EXT-cover")
    result = await pipeline.run(state)
    assert (result.end.status, result.end.skipped) == (RunStatus.FAILED, ("audit", "report"))
    assert result.end.error.startswith("SectionError: EXT-balance failed: ProviderError: provider down")


@pytest.mark.parametrize("source", [None, ""], ids=["absent", "empty"])
async def test_a_run_without_its_source_names_what_it_lacks(
    pipeline: InstrumentGraph, state: RunState, source: str | None
) -> None:
    del state.context["source"]
    _ = state.context.update({"source": source}) if source is not None else None
    result = await pipeline.run(state)
    assert (result.end.status, result.end.skipped) == (RunStatus.FAILED, ("extract", "audit", "report"))
    assert "the run needs `source`, the path of the document to read" in result.end.error
