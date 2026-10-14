"""tests/integration: pipelines.note.graph — an autocallable read by the real model, held to its curated truth.

The fused calls reach the model each tier names (the local vLLM unless AGENT_HIGH/MEDIUM/LOW say
otherwise) and replay from cassettes; docling replays from its recorded spans. What is pinned is the
document's own ground — identifiers, money, levels, calendar — and that every audit held: the
classification, the summary and the payoff prose are the model's word, judged by the checks, never
pinned to a phrasing. Re-record with `make record`."""

from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

import eserde
import pytest

from adapters.otel import OtelAdapter
from core.settings.otel import OtelSettings
from core.state import State
from e_graph.instrument.models import RunStatus
from e_graph.instrument.state import ContextState, InfraState, ProcessorsState, RunState
from e_graph.instrument.telemetry import InstrumentTelemetry
from e_graph.logic.orchestrator.core import OrchestratorCore
from e_graph.pipelines.note.graph import NoteGraph
from processors.doc import DocProcessor
from support.docling import GoldenPort

if TYPE_CHECKING:
    from e_graph.logic.agent import AgnosticAgent

pytestmark = [pytest.mark.vcr, pytest.mark.integration]

DOCUMENTS: Final[Path] = Path(__file__).resolve().parents[5] / "tests" / "resources" / "documents"
NOTE: Final[str] = "bofa-autocall-2027.pdf"


async def read(agent: AgnosticAgent) -> tuple[RunStatus, dict[str, Any]]:
    """The whole pipeline over the note: the verdict and the record."""
    async with OtelAdapter(OtelSettings()) as telemetry:
        infra = InfraState(
            adapters=None,  # ty: ignore[invalid-argument-type]
            processors=ProcessorsState(doc=DocProcessor(GoldenPort())),
            agent=agent,
            orchestrator=OrchestratorCore(),
            telemetry=InstrumentTelemetry(telemetry),
            graphs=MappingProxyType({}),
        )
        system = State(infra=infra, contexts=ContextState())
        system.seal()
        state = RunState(system, pipeline="note")
        state.context.source = str(DOCUMENTS / "notes" / NOTE)
        result = await NoteGraph().build().run(state, retain=True)
        return result.end.status, dict(state.context.report.get("REP-termsheet", {}))


def truth() -> dict[str, Any]:
    corpus = eserde.load(DOCUMENTS / "corpus.yaml")
    return next(entry["truth"] for entry in corpus["documents"] if entry["file"] == f"notes/{NOTE}")


@pytest.mark.timeout(900)
async def test_the_note_reads_its_ground_truth(agent: AgnosticAgent) -> None:
    expected = truth()
    status, record = await read(agent)
    assert status is RunStatus.SUCCEEDED, "the note's run did not reach report"
    assert (record["isin"], record["cusip"]) == (expected["isin"], expected["cusip"])
    assert (record["issuer"], record["guarantor"]) == (expected["issuer"], expected["guarantor"])
    assert record["underlier"]["ticker"] == expected["underlier_ticker"]
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
    assert len(record["summary"]) >= 200
