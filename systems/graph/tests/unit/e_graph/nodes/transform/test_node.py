"""tests/unit: nodes.transform.node — the record mapped, the amount normalized through Decimal."""

from decimal import InvalidOperation
from typing import TYPE_CHECKING

import pytest

from e_graph.nodes.transform.node import node_transform

if TYPE_CHECKING:
    from e_graph.instrument.state import RunState


def seed(state: RunState, amount: str) -> None:
    state.context.update({"kind": "invoice", "digest": "d1", "amount": amount})


async def test_transform_maps_the_record(run_state: RunState) -> None:
    seed(run_state, "3.50")
    assert await node_transform(run_state) is None
    assert run_state.context.record == {"kind": "invoice", "digest": "d1", "amount": "3.50"}


async def test_transform_refuses_an_empty_amount(run_state: RunState) -> None:
    seed(run_state, "")
    with pytest.raises(InvalidOperation):
        await node_transform(run_state)
