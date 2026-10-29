"""tests/integration: pipelines.note.graph — two issuers' 424B2s read by the real model, held to their curated truth.

The generality gate for the note pipeline: BofA's index-linked note and Barclays' single-stock,
unguaranteed, memory-coupon note. The fused calls reach the model each tier names and replay from
cassettes; docling replays from recorded spans. What is pinned is the document's own ground — money,
levels, calendar, identifiers — and that every audit held: classification, summary and payoff prose are
the model's word, judged by the checks, never pinned to a phrasing. Re-record with `make record`."""

from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

import eserde
import pytest

from adapters.otel import OtelAdapter
from e_graph.instrument.contexts import InstrumentContexts
from e_graph.instrument.models import RunStatus
from e_graph.instrument.state import InfraState, InstrumentState, ProcessorsState, RunState
from e_graph.instrument.telemetry import InstrumentTelemetry
from e_graph.logic.orchestrator.core import OrchestratorCore
from e_graph.logic.state import LogicState
from e_graph.pipelines.note.graph import NoteGraph
from infra.config.otel import OtelSettings
from infra.state import State
from processors.doc import DocProcessor
from support.docling import GoldenPort

if TYPE_CHECKING:
    from e_graph.logic.agent import AgnosticAgent

pytestmark = [pytest.mark.vcr, pytest.mark.integration]

DOCUMENTS: Final[Path] = Path(__file__).resolve().parents[5] / "tests" / "resources" / "documents"
NOTES: Final[str] = "notes"

### the two readings the truth pins, per note — the money, levels and calendar the document states,
### and the guarantor's presence or absence, which is the shape the generalization had to learn.
CASES: Final[dict[str, dict[str, Any]]] = {
    "bofa-autocall-2027.pdf": {
        "issuer": "BofA Finance LLC",
        "guarantor": "Bank of America Corporation",
        "ticker": "SPX",
    },
    "barclays-acn-2029.pdf": {"issuer": "Barclays Bank PLC", "guarantor": None, "ticker": "ACN"},
}


async def read(agent: AgnosticAgent, note: str) -> tuple[RunStatus, dict[str, Any]]:
    """The whole pipeline over one note: the verdict and the record."""
    async with OtelAdapter(OtelSettings()) as telemetry:
        infra = InfraState(
            adapters=None,  # ty: ignore[invalid-argument-type]
            processors=ProcessorsState(doc=DocProcessor(GoldenPort())),
            graphs=MappingProxyType({}),
        )
        system = State(
            infra=infra,
            logic=LogicState(agent=agent, orchestrator=OrchestratorCore()),
            instrument=InstrumentState(telemetry=InstrumentTelemetry(telemetry), contexts=InstrumentContexts()),
        )
        system.seal()
        state = RunState(system, pipeline="note")
        state.context.source = str(DOCUMENTS / NOTES / note)
        result = await NoteGraph().build().run(state, retain=True)
        return result.end.status, dict(state.context.report.get("REP-termsheet", {}))


def truth(note: str) -> dict[str, Any]:
    corpus = eserde.load(DOCUMENTS / "corpus.yaml")
    return next(entry["truth"] for entry in corpus["documents"] if entry["file"] == f"{NOTES}/{note}")


@pytest.mark.parametrize("note", list(CASES))
@pytest.mark.timeout(900)
async def test_a_424b2_reads_into_its_term_sheet_held_to_the_truth(agent: AgnosticAgent, note: str) -> None:
    expected = truth(note)
    status, record = await read(agent, note)
    assert status is RunStatus.SUCCEEDED, "the note's run did not reach report"
    assert (record["isin"], record["cusip"]) == (expected["isin"], expected["cusip"])
    assert (record["issuer"], record["guarantor"]) == (CASES[note]["issuer"], CASES[note]["guarantor"])
    assert record["underlier"]["ticker"] == CASES[note]["ticker"]
    assert record["money"]["aggregate_principal"] == expected["aggregate_principal"]
    assert record["money"]["estimated_value"] == expected["estimated_value"]
    assert record["coupon"] == {
        "rate_percent": expected["coupon_rate"],
        "quarterly_per_note": expected["coupon_payment"],
        "payments": len(expected["observations"]),
    }
    assert record["levels"] == {
        "initial_value": expected["initial_value"],
        "coupon_barrier": expected["coupon_barrier"],
        "downside_threshold": expected["downside_threshold"],
        "call_level": expected["call_threshold"],
    }
    assert record["calendar"]["maturity_date"] == expected["maturity_date"]
    assert record["verdict"]["holds"] is True, record["verdict"]
    assert record["verdict"]["coherent"] is True, record["verdict"]
    assert record["classification"]["eusipa"] == "yield enhancement"
    assert len(record["summary"]) >= 120
