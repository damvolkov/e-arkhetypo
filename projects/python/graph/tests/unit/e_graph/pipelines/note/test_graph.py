"""tests/unit: pipelines.note.graph — a 424B2 read into its term sheet, the agent scripted, docling replayed.

The ingest is real (liteparse in-process, docling's recorded spans); the agent answers every semantic
spec as the pricing supplement prints it, so what is tested is everything around the model: the regexes
and the table parsing, the ISO normalization, the fused calls per tier, the deterministic derivations,
the identity and order audits, and the record — all held to the truth curated from the document."""

import copy
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

import pytest

from e_graph.instrument.contexts import InstrumentContexts
from e_graph.instrument.models import RunStatus
from e_graph.instrument.state import InfraState, InstrumentState, ProcessorsState, RunState
from e_graph.instrument.telemetry import InstrumentTelemetry
from e_graph.logic.models import Tier
from e_graph.logic.orchestrator.core import OrchestratorCore
from e_graph.logic.state import LogicState
from e_graph.models.section import Section
from e_graph.pipelines.note.graph import NoteGraph
from infra.state import State
from processors.doc import DocProcessor
from support.darts import ScriptedAgent
from support.docling import GoldenPort

if TYPE_CHECKING:
    from pytest_resources import Resources

    from e_graph.instrument.graph import InstrumentGraph
    from e_graph.logic.models import SectionPlan

NOTES = Path(__file__).resolve().parents[5] / "tests" / "resources" / "documents" / "notes"
PAYMENT_DATES: Final = (
    "February 10, 2026",
    "May 8, 2026",
    "August 10, 2026",
    "November 10, 2026",
    "February 10, 2027",
    "May 10, 2027",
    "August 10, 2027",
    "November 12, 2027",
)

ANSWERS: Final[dict[str, Any]] = {
    "EXT-issuer": {
        "issuer": "BofA Finance LLC",
        "guarantor": "Bank of America Corporation",
        "senior_unsecured": True,
    },
    "EXT-underlier": {"name": "S&P 500 Index", "ticker": "SPX", "is_index": True},
    "EXT-coupon": {"rate_percent": 9.60, "quarterly_payment": 0.24, "frequency": "quarterly"},
    "EXT-autocall": {
        "initial_value": 6720.32,
        "call_level": 6720.32,
        "payout": "the Stated Principal Amount plus the Contingent Coupon Payment",
        "callable_on_final": False,
    },
    "EXT-barrier": {
        "coupon_barrier": 5040.24,
        "downside_threshold": 5040.24,
        "share_of_initial_percent": 75.0,
    },
    "EXT-dates": {
        "pricing_date": "2025-11-06",
        "issue_date": "2025-11-12",
        "final_observation_date": "2027-11-08",
        "maturity_date": "2027-11-12",
    },
    "EXT-estimated-value": {"estimated_value": 9.938, "offering_price": 10.0},
    "EXT-agents": {
        "calculation_agent": "BofA Securities, Inc.",
        "selling_agents": ["BofA Securities, Inc.", "UBS Financial Services Inc."],
    },
    "EXT-listing": {"listed": False},
    "EXT-market-maker": {"market_maker": "BofAS", "obligated": False, "limited_liquidity": True},
    "EXT-tax": {
        "position": "The notes are expected to be contingent income-bearing, single financial contracts with respect to the underlying.",
        "uncertain": True,
        "withholding_percent": 30.0,
    },
    "EXT-risks": {
        "max_loss_percent": 100.0,
        "risks": [
            "credit risk of BofA Finance and the guarantor",
            "market risk of the S&P 500 Index",
            "no listing and limited liquidity",
        ],
    },
    "EXT-payoff": {
        "coupon": "A Contingent Coupon Payment of $0.24 per $10.00 if the Observation Date closing level is at or above the Coupon Barrier.",
        "auto_call": "At par plus the coupon due if a quarterly Observation Date closes at or above the Initial Value, never on the final one.",
        "maturity_at_or_above": "The Stated Principal Amount plus the final Contingent Coupon Payment.",
        "maturity_below": "Less than the Stated Principal Amount: the principal is marked to the index.",
        "loss_formula": "a loss proportionate to the decline of the Underlying, up to 100%.",
    },
    "EXT-coupon-schedule": {"payments": [{"payment_date": printed, "amount": 0.24} for printed in PAYMENT_DATES]},
    "EXT-identifiers-read": {"cusip": "09711E688", "isin": "US09711E6885"},
    "AUD-coherence": {"coherent": True, "conflicts": 0, "worst_field": ""},
    "INF-product-type": {
        "family": "yield enhancement",
        "shape": "trigger autocallable contingent yield note",
        "capital_at_risk": True,
    },
    "INF-cfi": {"code": "DMXIXX", "reason": "debt, other group, attributes mostly unspecified"},
    "INF-risk-class": {
        "risk_class": 5,
        "reasons": [
            "full downside to the final observation",
            "contingent coupons can be skipped",
            "issuer and guarantor credit risk",
            "no listing, limited liquidity",
        ],
    },
    "INF-summary": {
        "summary": (
            "You lend ten dollars per note to BofA Finance, guaranteed by Bank of America, for two years "
            "or until the S&P 500 closes at or above its starting level on a quarterly observation. Each "
            "quarter you may receive 24 cents if the index holds above 75% of its start; below that, the "
            "quarter pays nothing. If the index reaches its start level, the note ends early with your "
            "ten dollars and that quarter's cents. At maturity you get your ten dollars back while the "
            "index stays above 75% of where it began; below that, you lose exactly what the index lost, "
            "and it can take the whole ten dollars. There is no exchange listing, so selling early means "
            "accepting whatever the bank quotes."
        )
    },
}


@pytest.fixture
def agent() -> ScriptedAgent:
    scripted = ScriptedAgent()
    scripted.answers.update(copy.deepcopy(ANSWERS))
    return scripted


@pytest.fixture
def orchestrator() -> OrchestratorCore:
    return OrchestratorCore()


@pytest.fixture
def state(agent: ScriptedAgent, orchestrator: OrchestratorCore) -> RunState:
    infra = InfraState(
        adapters=None,  # ty: ignore[invalid-argument-type]
        processors=ProcessorsState(doc=DocProcessor(GoldenPort())),
        graphs=MappingProxyType({}),
    )
    system = State(
        infra=infra,
        logic=LogicState(agent=agent, orchestrator=orchestrator),  # ty: ignore[invalid-argument-type]
        instrument=InstrumentState(telemetry=InstrumentTelemetry(), contexts=InstrumentContexts()),
    )
    system.seal()
    run = RunState(system, pipeline="note")
    run.context.source = str(NOTES / "bofa-autocall-2027.pdf")
    return run


@pytest.fixture
def pipeline() -> InstrumentGraph:
    return NoteGraph().build()


def test_the_graph_is_a_line_of_five_sections(pipeline: InstrumentGraph) -> None:
    assert [node.id for node in pipeline.topology().nodes] == ["ingest", "extract", "inference", "audit", "report"]
    assert pipeline.summary == "A 424B2 read into its term sheet: ingest → extract → inference → audit → report."


async def test_the_note_reads_into_its_term_sheet_held_to_the_truth(
    pipeline: InstrumentGraph, state: RunState, resources: Resources
) -> None:
    result = await pipeline.run(state, retain=True)
    assert result.end.status is RunStatus.SUCCEEDED, result.end.error
    truth = next(
        entry for entry in resources.documents["corpus"]["documents"] if entry["file"].startswith("notes/bofa")
    )["truth"]
    record = dict(state.context.report["REP-termsheet"])
    assert truth["isin"] == record["isin"]
    assert truth["cusip"] == record["cusip"]
    assert record["money"] == {
        "currency": "$",
        "aggregate_principal": truth["aggregate_principal"],
        "denomination": truth["denomination"],
        "offering_price": truth["offering_price"],
        "estimated_value": truth["estimated_value"],
        "fee_drag_percent": round(
            (truth["offering_price"] - truth["estimated_value"]) / truth["offering_price"] * 100, 4
        ),
    }
    assert record["coupon"] == {
        "rate_percent": truth["coupon_rate"],
        "quarterly_per_note": truth["coupon_payment"],
        "payments": len(truth["observations"]),
    }
    assert record["calendar"]["term_years"] == 2.0164
    assert record["levels"] == {
        "initial_value": truth["initial_value"],
        "coupon_barrier": truth["coupon_barrier"],
        "downside_threshold": truth["downside_threshold"],
        "call_level": truth["call_threshold"],
    }
    assert record["classification"] == {"eusipa": "yield enhancement", "shape": "trigger autocallable contingent yield note", "cfi": "DMXIXX", "risk_class": 5}  # fmt: skip
    assert record["outcome"] == {"best_percent": 2.4, "worst_percent": -100.0, "scenarios": 11}
    assert record["verdict"] == {"holds": True, "broken": [], "checks": 10, "coherent": True, "conflicts": 0}
    assert record["summary"] == ANSWERS["INF-summary"]["summary"]


async def test_the_extract_plan_runs_three_steps_with_four_parallel_groups_in_the_first(
    orchestrator: OrchestratorCore,
) -> None:
    plan = await orchestrator.plan("note", Section.EXTRACT)
    assert [step.index for step in plan.steps] == [0, 1, 2]
    assert plan.steps[0].deterministic == (
        "EXT-amounts",
        "EXT-fees",
        "EXT-identifiers",
        "EXT-registration",
        "EXT-schedule-table",
    )
    tiers = [(call.tier, call.specs) for call in plan.steps[0].fused]
    mediums = [specs for tier, specs in tiers if tier is Tier.MEDIUM]
    assert [tier for tier, _ in tiers] == [Tier.HIGH, Tier.MEDIUM, Tier.MEDIUM, Tier.LOW]
    assert len(mediums) >= 2
    assert sum(len(specs) for specs in mediums) == 9
    assert plan.steps[1].deterministic == ("EXT-schedule",)
    assert plan.steps[2].deterministic == ("EXT-terms",)
    assert plan.fallbacks == {"EXT-identifiers": "EXT-identifiers-read"}


async def test_the_medium_specs_split_into_parallel_calls_that_all_read_the_cover(
    pipeline: InstrumentGraph, state: RunState, agent: ScriptedAgent
) -> None:
    await pipeline.run(state, retain=True)
    mediums = [
        call for call in agent.calls if call["tier"] is Tier.MEDIUM and all(s.startswith("EXT-") for s in call["specs"])
    ]
    assert len(mediums) >= 2
    assert sum(len(call["specs"]) for call in mediums) == 9
    assert all("## Page 1" in call["prompt"] for call in mediums)
    highs = [call for call in agent.calls if call["tier"] is Tier.HIGH]
    (payoff,) = [call for call in highs if "EXT-payoff" in call["specs"]]
    assert payoff["specs"] == ("EXT-payoff",)
    assert payoff["schema"]["required"] == ["EXT-payoff"]


async def test_a_broken_identifier_is_rescued_by_the_semantic_reading(
    orchestrator: OrchestratorCore, state: RunState
) -> None:
    await orchestrator.run(Section.INGEST, state)
    pages = state.context.ingest["ING-document"]["pages"]
    pages[0]["markdown"] = pages[0]["markdown"].replace("09711E688 / US09711E6885", "09711E68 9 / US09711E68 85")
    run = await orchestrator.run(Section.EXTRACT, state)
    identifiers = next(outcome for outcome in run.outcomes if outcome.spec == "EXT-identifiers")
    assert (identifiers.status, identifiers.rescuer) == ("rescued", "EXT-identifiers-read")
    assert state.context.extract["EXT-identifiers"] == ANSWERS["EXT-identifiers-read"]


async def test_an_audit_that_does_not_hold_is_said_not_hidden(
    pipeline: InstrumentGraph, state: RunState, agent: ScriptedAgent
) -> None:
    agent.answers["EXT-barrier"] = {**ANSWERS["EXT-barrier"], "downside_threshold": 6040.24}
    result = await pipeline.run(state, retain=True)
    assert result.end.status is RunStatus.SUCCEEDED
    audit = state.context.audit
    assert (audit["AUD-thresholds"]["holds"], audit["AUD-value"]["holds"]) == (False, True)
    assert state.context.report["REP-termsheet"]["verdict"] == {
        "holds": False,
        "broken": ["AUD-thresholds"],
        "checks": 10,
        "coherent": True,
        "conflicts": 0,
    }


async def test_a_check_digit_that_fails_is_named_by_the_verdict(
    pipeline: InstrumentGraph, state: RunState, agent: ScriptedAgent
) -> None:
    agent.answers["EXT-estimated-value"] = {**ANSWERS["EXT-estimated-value"], "estimated_value": 10.0}
    await pipeline.run(state, retain=True)
    broken = state.context.report["REP-termsheet"]["verdict"]["broken"]
    assert broken == ["AUD-value"]


async def test_a_model_down_stops_the_run_at_inference(
    pipeline: InstrumentGraph, state: RunState, agent: ScriptedAgent
) -> None:
    agent.down.add("INF-cfi")
    result = await pipeline.run(state)
    assert (result.end.status, result.end.skipped) == (RunStatus.FAILED, ("audit", "report"))
    assert "INF-cfi failed" in result.end.error


@pytest.mark.parametrize(
    ("section", "expected"),
    [("inference", 4), ("audit", 2), ("report", 1)],
)
async def test_every_section_keeps_its_steps_apart(orchestrator: OrchestratorCore, section: str, expected: int) -> None:
    plan: SectionPlan = await orchestrator.plan("note", Section(section))
    assert len(plan.steps) == expected
