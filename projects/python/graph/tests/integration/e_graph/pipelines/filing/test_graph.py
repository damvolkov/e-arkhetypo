"""tests/integration: pipelines.filing.graph — two 10-Ks read by the real model, held to their XBRL truth.

The fused call reaches the model the MEDIUM tier names (the local vLLM unless AGENT_MEDIUM__* say
otherwise) and is replayed from its cassette; docling is replayed from its recorded spans. Apple's filing
reads whole and exact. Coca-Cola's income statement, total assets and cash read exact; its liabilities and
equity do not — docling's table model splits that sheet's labels from its figures, and the model fills the
gap. Measured 2026-10-14 over three runs: once the balance audit caught the read, once the model's figures
were wrong yet summed to the assets, and the audit — an identity, not an oracle — let them through."""

from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

import eserde
import pytest

from adapters.otel import OtelAdapter
from e_graph.instrument.models import RunStatus
from e_graph.instrument.state import ContextState, InfraState, ProcessorsState, RunState
from e_graph.instrument.telemetry import InstrumentTelemetry
from e_graph.logic.orchestrator.core import OrchestratorCore
from e_graph.pipelines.filing.graph import FilingGraph
from infra.settings.otel import OtelSettings
from infra.state import State
from processors.doc import DocProcessor
from support.docling import GoldenPort

if TYPE_CHECKING:
    from e_graph.logic.agent import AgnosticAgent

pytestmark = [pytest.mark.vcr, pytest.mark.integration]

FILINGS: Final[Path] = Path(__file__).resolve().parents[5] / "tests" / "resources" / "documents" / "filings"
INCOME: Final[tuple[str, ...]] = (
    "revenue",
    "cost_of_revenue",
    "gross_profit",
    "operating_income",
    "net_income",
    "eps_basic",
    "eps_diluted",
)


async def read(agent: AgnosticAgent, file: str) -> tuple[RunStatus, dict[str, Any], dict[str, Any]]:
    """One filing through the whole pipeline: the verdict, the record, the audits."""
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
        state = RunState(system, pipeline="filing")
        state.context.source = str(FILINGS / file)
        result = await FilingGraph().build().run(state, retain=True)
        audits = {name: dict(verdict) for name, verdict in state.context.audit.items()}
        return result.end.status, dict(state.context.report.get("REP-facts", {})), audits


def truth(file: str) -> dict[str, Any]:
    corpus = eserde.load(FILINGS.parent / "corpus.yaml")
    return next(entry["truth"] for entry in corpus["documents"] if entry["file"] == f"filings/{file}")


### recording waits on the model; the replay takes milliseconds.
@pytest.mark.timeout(600)
async def test_apple_reads_whole_and_exact(agent: AgnosticAgent) -> None:
    status, record, audits = await read(agent, "aapl-10k-2025.pdf")
    expected = truth("aapl-10k-2025.pdf")
    assert status is RunStatus.SUCCEEDED
    assert (record["company"], record["period_end"], record["shares_outstanding"]) == (
        expected["company"],
        expected["period_end"],
        expected["shares_outstanding"]["value"],
    )
    assert record["facts"] == {name: expected["facts"][name]["value"] for name in record["facts"]}
    assert (len(record["facts"]), record["broken"], {verdict["holds"] for verdict in audits.values()}) == (
        11,
        [],
        {True},
    )


@pytest.mark.timeout(600)
async def test_coca_cola_reads_its_income_statement_exact(agent: AgnosticAgent) -> None:
    status, record, audits = await read(agent, "ko-10k-2025.pdf")
    expected = truth("ko-10k-2025.pdf")
    assert status is RunStatus.SUCCEEDED
    assert (record["company"], record["period_end"]) == (expected["company"], expected["period_end"])
    assert {name: record["facts"][name] for name in INCOME} == {
        name: expected["facts"][name]["value"] for name in INCOME
    }
    assert (record["facts"]["total_assets"], record["facts"]["cash"]) == (
        expected["facts"]["total_assets"]["value"],
        expected["facts"]["cash"]["value"],
    )
    ### what docling split apart (the sheet's liabilities and equity) is no reliable read: no value is pinned for it.
    assert audits["AUD-margin"]["holds"] is True
