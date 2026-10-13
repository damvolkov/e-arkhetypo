"""tests/unit: instrument.errors — the rule and the subject travel with the message."""

from datetime import UTC, datetime

from e_graph.instrument.errors import ContractError, ContractRule, NodeError
from e_graph.instrument.models import NodeOutput, NodeRole, NodeStatus


def test_contract_error_names_rule_and_subject() -> None:
    error = ContractError(ContractRule.ASYNC, "node_x", "must be `async def`")
    assert (error.rule, error.subject) == (ContractRule.ASYNC, "node_x")
    assert str(error) == "[async] node_x: must be `async def`"
    assert isinstance(error, TypeError)


def test_node_error_carries_the_failed_output() -> None:
    output = NodeOutput(
        run_id="r",
        name="n",
        category="extract",
        role=NodeRole.MID,
        status=NodeStatus.FAILED,
        at=datetime.now(UTC),
        error="ValueError: x",
    )
    error = NodeError(output)
    assert error.output is output
    assert str(error) == "ValueError: x"
    assert isinstance(error, RuntimeError)
