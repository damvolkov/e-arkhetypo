"""tests/unit: logic.orchestrator.fusion — briefs, shared material, the fused schema, the split, the packing."""

import jsonschema_rs
import pytest

from e_graph.logic.models import JsonSchema, SemanticSpec, SpecNode
from e_graph.logic.orchestrator.fusion import BARE, PREAMBLE, SpecFusion

TOTAL = JsonSchema({"type": "object", "properties": {"total": {"type": "number"}}, "required": ["total"]})


def node(name: str, **fields: object) -> SpecNode:
    values = {"description": f"The {name}.", "instructions": f"Read the {name}.", "output": TOTAL, **fields}
    return SpecNode(spec=SemanticSpec(name=name, **values), file=f"{name}.yaml")  # ty: ignore[invalid-argument-type]


def test_a_brief_carries_everything_a_spec_tells_the_agent() -> None:
    brief = SpecFusion.brief(
        node("EXT-total", examples=({"total": 2.5},), wiki=("net-amount", "gross")),
        {"net-amount": "# Net\nAfter tax.\n", "other": "x"},
    )
    assert brief.splitlines()[:3] == ["### EXT-total", "The EXT-total.", "Read the EXT-total."]
    assert 'Example answer: {"total":2.5}' in brief
    assert "Glossary, net-amount:\n# Net\nAfter tax." in brief
    assert "gross" not in brief


def test_instructions_open_with_the_preamble_and_keep_spec_order() -> None:
    text = SpecFusion.instructions([node("EXT-b"), node("EXT-a")], {})
    assert text.startswith(PREAMBLE)
    assert text.index("### EXT-b") < text.index("### EXT-a")


def test_shared_material_is_sent_once_for_every_spec_sharing_it() -> None:
    prompt = SpecFusion.prompt({"EXT-a": "page 44", "EXT-b": "page 44", "EXT-c": "page 10", "EXT-d": "  "})
    assert prompt.count("page 44") == 1
    assert "### Material for EXT-a, EXT-b\npage 44" in prompt
    assert "### Material for EXT-c\npage 10" in prompt
    assert "EXT-d" not in prompt
    assert SpecFusion.prompt({"EXT-a": ""}) == BARE


def test_the_fused_schema_is_one_closed_object_of_spec_outputs() -> None:
    schema = SpecFusion.schema([node("EXT-a"), node("EXT-b")])
    validator = jsonschema_rs.validator_for(schema)
    assert validator.is_valid({"EXT-a": {"total": 1}, "EXT-b": {"total": 2}})
    assert not validator.is_valid({"EXT-a": {"total": 1}})
    assert not validator.is_valid({"EXT-a": {"total": 1}, "EXT-b": {"total": "x"}})
    assert not validator.is_valid({"EXT-a": {"total": 1}, "EXT-b": {"total": 2}, "EXT-c": {}})
    assert SpecFusion.split({"EXT-a": {"total": 1}, "EXT-b": {"total": 2}}, ["EXT-b"]) == {"EXT-b": {"total": 2}}


def test_weight_grows_with_brief_schema_and_material() -> None:
    bare = SpecFusion.weight(node("EXT-a"), {})
    assert SpecFusion.weight(node("EXT-a"), {}, "x" * 400) == bare + 100
    assert SpecFusion.tokens("abcde") == 2


@pytest.mark.parametrize(
    ("weights", "budget", "most", "calls"),
    [
        ({}, 100, 8, []),
        ({"a": 10, "b": 20, "c": 30}, 100, 8, [("a", "b", "c")]),
        ({"a": 60, "b": 50, "c": 40}, 100, 8, [("a", "c"), ("b",)]),
        ({"a": 500, "b": 10}, 100, 8, [("a",), ("b",)]),
        ({"a": 1, "b": 1, "c": 1}, 100, 2, [("a", "b"), ("c",)]),
        ({"b": 5, "a": 5}, 100, 1, [("a",), ("b",)]),
    ],
    ids=["nothing", "all-fit", "first-fit-decreasing", "heavy-alone", "most-specs", "ties-by-name"],
)
def test_pack_first_fit_decreasing(
    weights: dict[str, int], budget: int, most: int, calls: list[tuple[str, ...]]
) -> None:
    assert SpecFusion.pack(weights, budget, most) == calls
