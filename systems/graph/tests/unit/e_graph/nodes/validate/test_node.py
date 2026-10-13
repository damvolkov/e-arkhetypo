"""tests/unit: nodes.validate.node — the numeric check and the router that draws the loop."""

from typing import TYPE_CHECKING

import pytest

from e_graph.nodes.validate.node import ATTEMPTS, node_validate, route_validate

if TYPE_CHECKING:
    from e_graph.instrument.state import RunState


@pytest.mark.parametrize(("amount", "verdict"), [("1250.00", "valid"), ("", "invalid"), ("1.2.3", "invalid")])
async def test_validate_checks_the_amount(run_state: RunState, amount: str, verdict: str) -> None:
    run_state.context.amount = amount
    assert await node_validate(run_state) == verdict


@pytest.mark.parametrize(("attempts", "target"), [(1, "extract"), (ATTEMPTS, "transform"), (ATTEMPTS + 1, "transform")])
def test_route_validate_retries_once(run_state: RunState, attempts: int, target: str) -> None:
    run_state.context.attempts = attempts
    assert route_validate(run_state) == target
