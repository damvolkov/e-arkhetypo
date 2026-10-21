"""tests/unit: instrument.node — every contract rule, the derived name, category and headline."""

import dataclasses
from typing import TYPE_CHECKING, Any, cast

import pytest

from e_graph.instrument.errors import ContractError, ContractRule
from e_graph.instrument.graph import InstrumentGraph
from e_graph.instrument.models import NodeOutput, NodeRole, NodeStatus
from e_graph.instrument.node import InstrumentNode
from e_graph.instrument.state import RunState
from e_graph.logic.agent import METER, UsageMeter
from e_graph.logic.errors import TruncatedError
from e_graph.logic.models import Usage
from e_graph.models.section import Section

if TYPE_CHECKING:
    from collections.abc import Callable


async def node_probe(state: RunState) -> str | None:
    """Probe the instrument.

    The headline is the first line only."""
    return None


def test_validate_derives_the_name(located: Callable[..., Any]) -> None:
    assert InstrumentNode.validate(located(node_probe)) == "probe"


def test_validate_rejects_sync(located: Callable[..., Any]) -> None:
    def node_sync(state: RunState) -> None: ...

    with pytest.raises(ContractError) as caught:
        InstrumentNode.validate(located(node_sync))
    assert caught.value.rule is ContractRule.ASYNC


def test_validate_rejects_non_function() -> None:
    with pytest.raises(ContractError) as caught:
        InstrumentNode.validate(object())  # ty: ignore[invalid-argument-type]
    assert caught.value.rule is ContractRule.ASYNC


def test_validate_rejects_bad_name(located: Callable[..., Any]) -> None:
    async def probe(state: RunState) -> None: ...

    with pytest.raises(ContractError) as caught:
        InstrumentNode.validate(located(probe))
    assert caught.value.rule is ContractRule.NAME


def test_validate_rejects_wrong_location() -> None:
    with pytest.raises(ContractError) as caught:
        InstrumentNode.validate(node_probe)
    assert caught.value.rule is ContractRule.LOCATION


def test_validate_rejects_extra_parameters(located: Callable[..., Any]) -> None:
    async def node_two(state: RunState, extra: int) -> None: ...

    with pytest.raises(ContractError) as caught:
        InstrumentNode.validate(located(node_two))
    assert caught.value.rule is ContractRule.SIGNATURE


def test_validate_rejects_keyword_only(located: Callable[..., Any]) -> None:
    async def node_kw(*, state: RunState) -> None: ...

    with pytest.raises(ContractError) as caught:
        InstrumentNode.validate(located(node_kw))
    assert caught.value.rule is ContractRule.SIGNATURE


def test_validate_rejects_foreign_state(located: Callable[..., Any]) -> None:
    async def node_dict(state: dict) -> None: ...

    with pytest.raises(ContractError) as caught:
        InstrumentNode.validate(located(node_dict))
    assert caught.value.rule is ContractRule.STATE


def test_validate_rejects_unresolvable_hint(located: Callable[..., Any]) -> None:
    async def node_ghost(state: Ghost) -> None: ...  # noqa: F821  # ty: ignore[unresolved-reference]

    with pytest.raises(ContractError) as caught:
        InstrumentNode.validate(located(node_ghost))
    assert caught.value.rule is ContractRule.STATE


def test_validate_rejects_wrong_return(located: Callable[..., Any]) -> None:
    async def node_number(state: RunState) -> int:
        return 0

    with pytest.raises(ContractError) as caught:
        InstrumentNode.validate(located(node_number))
    assert caught.value.rule is ContractRule.RETURN


def test_validate_rejects_missing_return(located: Callable[..., Any]) -> None:
    async def node_bare(state: RunState): ...

    with pytest.raises(ContractError) as caught:
        InstrumentNode.validate(located(node_bare))
    assert caught.value.rule is ContractRule.RETURN


@pytest.mark.parametrize(("folder", "category"), [("extract", Section.EXTRACT), ("notify", "notify")])
def test_category_section_or_custom_folder(located: Callable[..., Any], folder: str, category: str) -> None:
    graph = InstrumentGraph().add_node(located(node_probe, folder))
    node = graph.nodes["probe"]
    assert isinstance(node, InstrumentNode)
    assert node.category == category
    assert type(node.category) is (Section if folder == "extract" else str)
    assert node.doc == "Probe the instrument."


async def node_fails(state: RunState) -> None:
    """Fails on purpose."""
    msg = "broken input"
    raise ValueError(msg)


##### RUN — the wrapper's own contract: RunState in, NodeOutput out, always #####
async def test_run_outside_a_graph_answers_succeeded(located: Callable[..., Any], run_state: RunState) -> None:
    node = InstrumentGraph().add_node(located(node_probe)).nodes["probe"]
    assert isinstance(node, InstrumentNode)
    output = await node.run(run_state)
    assert isinstance(output, NodeOutput)
    assert (output.name, output.status, output.summary) == ("probe", NodeStatus.SUCCEEDED, "Probe the instrument.")
    assert output.role is NodeRole.MID
    assert output.latency_ms >= 0
    assert len(output.trace_id) == 32


async def test_run_turns_a_raise_into_failed(located: Callable[..., Any], run_state: RunState) -> None:
    node = InstrumentGraph().add_node(located(node_fails)).nodes["fails"]
    assert isinstance(node, InstrumentNode)
    output = await node.run(run_state)
    assert (output.status, output.error, output.summary) == (NodeStatus.FAILED, "ValueError: broken input", "")
    assert len(output.span_id) == 16


##### RESULT — what a node returns folds into the instrument's output #####
async def node_mapping(state: RunState) -> dict[str, Any]:
    """Mapping headline."""
    return {"summary": "from dict", "latency_ms": 99.0, "status": "failed", "pages": 3}


async def node_drafted(state: RunState) -> NodeOutput:
    """Drafted headline."""
    return NodeOutput(error="kept", extra={"seen": True})


async def node_rogue(state: RunState) -> int:
    """Lies about its return."""
    return 7


async def node_spends(state: RunState) -> str:
    """Spends on the agent."""
    ### what the agent does after every call: add its usage to the meter the instrument opened.
    cast("UsageMeter", METER.get()).add(Usage(input_tokens=4, output_tokens=1, total_tokens=5, calls=1))
    return "spent"


async def test_run_dict_fills_empty_slots_rest_extra(located: Callable[..., Any], run_state: RunState) -> None:
    node = InstrumentGraph().add_node(located(node_mapping)).nodes["mapping"]
    assert isinstance(node, InstrumentNode)
    output = await node.run(run_state)
    assert (output.summary, output.status, output.extra) == ("from dict", NodeStatus.SUCCEEDED, {"pages": 3})
    assert output.latency_ms != 99.0
    assert output.usage is None


async def test_run_node_output_merges_its_fields(located: Callable[..., Any], run_state: RunState) -> None:
    node = InstrumentGraph().add_node(located(node_drafted)).nodes["drafted"]
    assert isinstance(node, InstrumentNode)
    output = await node.run(run_state)
    assert (output.summary, output.error, output.extra) == ("Drafted headline.", "kept", {"seen": True})
    assert output.status is NodeStatus.SUCCEEDED


async def test_run_unknown_result_fails_the_node(located: Callable[..., Any], run_state: RunState) -> None:
    ### the static contract is bypassed on purpose: the runtime guard is the last line.
    probe = InstrumentGraph().add_node(located(node_probe)).nodes["probe"]
    node = dataclasses.replace(cast("InstrumentNode", probe), func=located(node_rogue))
    output = await node.run(run_state)
    assert (output.status, output.error) == (
        NodeStatus.FAILED,
        "TypeError: a node returns str | dict | NodeOutput | None, not int",
    )


async def test_run_reports_agent_usage(located: Callable[..., Any], run_state: RunState) -> None:
    node = InstrumentGraph().add_node(located(node_spends)).nodes["spends"]
    assert isinstance(node, InstrumentNode)
    output = await node.run(run_state)
    assert output.usage == Usage(input_tokens=4, output_tokens=1, total_tokens=5, calls=1)


async def node_cut(state: RunState) -> str:
    """Spends, then the reply comes back cut."""
    cast("UsageMeter", METER.get()).add(Usage(input_tokens=4, output_tokens=8, total_tokens=12, calls=1))
    usage, msg = Usage(output_tokens=8, calls=1), "qwen reply cut at the token limit, max_tokens=8"
    raise TruncatedError(msg, raw="{", attempts=1, usage=usage, finish="length")


async def test_run_agent_failure_traced_on_the_output(located: Callable[..., Any], run_state: RunState) -> None:
    node = InstrumentGraph().add_node(located(node_cut)).nodes["cut"]
    assert isinstance(node, InstrumentNode)
    output = await node.run(run_state)
    assert output.status is NodeStatus.FAILED
    assert output.error == (
        "TruncatedError: qwen reply cut at the token limit, max_tokens=8 [finish=length, attempts=1, output_tokens=8]"
    )
    assert output.usage == Usage(input_tokens=4, output_tokens=8, total_tokens=12, calls=1)
