"""tests/unit: nodes.extract.node — attempts counted, amount found or missing, the injected failure."""

from typing import TYPE_CHECKING

import pytest

from e_graph.nodes.extract.node import node_extract

if TYPE_CHECKING:
    from e_graph.instrument.state import RunState


async def test_extract_counts_attempts_and_finds_the_total(run_state: RunState) -> None:
    run_state.context.canonical = "invoice 42 total 1250.00 eur"
    assert await node_extract(run_state) == {"summary": "attempt 1: amount 1250.00", "attempt": 1, "amount": "1250.00"}
    assert (await node_extract(run_state))["attempt"] == 2


async def test_extract_reports_a_missing_amount(run_state: RunState) -> None:
    run_state.context.canonical = "receipt without total"
    assert await node_extract(run_state) == {"summary": "attempt 1: amount missing", "attempt": 1, "amount": ""}
    assert run_state.context.amount == ""


async def test_extract_fails_on_demand(run_state: RunState) -> None:
    run_state.context.fail = True
    with pytest.raises(RuntimeError, match="on purpose"):
        await node_extract(run_state)
