"""tests/integration: logic.orchestrator — two semantic specs fused into one real call, a deterministic one on their answers.

The fused call reaches the model the MEDIUM tier names (the local vLLM unless AGENT_MEDIUM__* say
otherwise) and is replayed from its cassette; the answers are held to the 10-K's XBRL truth."""

from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest

from e_graph.logic.agent import AgnosticAgent
from e_graph.logic.models import SpecStatus
from infra.config.otel import OtelSettings
from providers.drivers.otel import OtelDriver
from support.crafter import SpecCrafter
from support.darts import DartsHarness

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_resources import Resources

pytestmark = [pytest.mark.vcr, pytest.mark.integration]

STATEMENT = """Apple Inc. CONSOLIDATED STATEMENTS OF OPERATIONS (In millions, except per-share amounts)
| | 2025 | 2024 | 2023 |
| Total net sales | 416,161 | 391,035 | 383,285 |
| Total cost of sales | 220,960 | 210,352 | 214,137 |
| Gross margin | 195,201 | 180,683 | 169,148 |
| Net income | $ 112,010 | $ 93,736 | $ 96,995 |"""
MILLIONS = {"type": "object", "properties": {"millions": {"type": "number"}}, "required": ["millions"]}
RATIO = {"type": "object", "properties": {"margin": {"type": "number"}}, "required": ["margin"]}


### recording waits on a reasoning model; the replay takes milliseconds.
@pytest.mark.timeout(600)
async def test_fused_specs_read_the_statement(resources: Resources, tmp_path: Path, settings: Any) -> None:
    async with (
        AgnosticAgent(settings.model_copy(update={"agent_timeout": timedelta(minutes=8)})) as agent,
        OtelDriver(OtelSettings()) as telemetry,
    ):
        ### a reasoning model answering two specs at once: deadlines sized for the recording, not the replay.
        darts = DartsHarness(
            SpecCrafter(resources, tmp_path, seed=1), telemetry, agent=agent, darts_timeout=timedelta(minutes=9)
        )
        for name, line in (("EXT-revenue", "total net sales"), ("EXT-net-income", "net income")):
            darts.semantic(
                name, output=MILLIONS, instructions=f"The fiscal 2025 {line}, in millions of US dollars, as a number."
            )
            darts.runner(name, pre_run=f"return {STATEMENT!r}")
        darts.deterministic("EXT-margin", output=RATIO, depends=("EXT-revenue", "EXT-net-income"))
        darts.runner(
            "EXT-margin",
            run='found = state.context.extract\nreturn {"margin": found["EXT-net-income"]["millions"] / found["EXT-revenue"]["millions"]}',
        )
        run, state = await darts.run()
    assert {outcome.status for outcome in run.outcomes} == {SpecStatus.SUCCEEDED}, [
        (o.spec, o.error) for o in run.outcomes
    ]
    written = darts.written(state)
    assert (written["EXT-revenue"]["millions"], written["EXT-net-income"]["millions"]) == (416161, 112010)
    assert round(written["EXT-margin"]["margin"], 4) == round(112010 / 416161, 4)
    ### one call answered both: the statement was sent once, for both specs.
    assert {outcome.call for outcome in run.outcomes if outcome.kind == "semantic"} == {0}
