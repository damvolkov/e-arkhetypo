"""tests/unit: nodes.report.node — e-serde serializes the record in the requested format."""

from typing import TYPE_CHECKING

import eserde
import pytest

from e_graph.nodes.report.node import node_report

if TYPE_CHECKING:
    from e_graph.instrument.state import RunState

RECORD: dict[str, str] = {"kind": "invoice", "digest": "d1", "amount": "3.50"}


@pytest.mark.parametrize("codec", [None, "json", "yaml", "toml"])
async def test_report_round_trips_through_eserde(run_state: RunState, codec: str | None) -> None:
    run_state.context.record = RECORD
    run_state.context.update({} if codec is None else {"format": codec})
    summary = await node_report(run_state)
    assert eserde.loads(run_state.context.report, format=codec or "json") == RECORD
    assert summary == f"delivered {len(run_state.context.report)} bytes as {codec or 'json'}"


async def test_report_refuses_an_unknown_format(run_state: RunState) -> None:
    run_state.context.record = RECORD
    run_state.context.format = "xml"
    with pytest.raises(KeyError, match="XML"):
        await node_report(run_state)
