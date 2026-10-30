"""tests/unit: logic.models — specs decoded per section: names, references, schema, examples, extension."""

from datetime import timedelta
from typing import Any

import msgspec
import pytest

from e_graph.logic.models import (
    Bound,
    DeterministicSpec,
    JsonSchema,
    Role,
    Runner,
    Scope,
    SemanticSpec,
    Slot,
    Spec,
    Tier,
)
from e_graph.models.section import PREFIXES, Section
from infra.struct import CheckedStruct

OUTPUT: dict[str, Any] = {"type": "object", "properties": {"total": {"type": "number"}}, "required": ["total"]}
NAME = Spec.named(Section.EXTRACT)
SEMANTIC: dict[str, Any] = {
    "kind": "semantic",
    "name": "EXT-total-amount",
    "description": "The invoice total.",
    "instructions": "Read the total.",
    "output": OUTPUT,
}
DETERMINISTIC: dict[str, Any] = {
    "kind": "deterministic",
    "name": "EXT-line-sum",
    "description": "Sum of the lines.",
    "runner": "owned/linesum",
    "output": OUTPUT,
}


def decode(raw: dict[str, Any], section: Section = Section.EXTRACT) -> Spec[str]:
    name = Spec.named(section)
    return CheckedStruct.convert(raw, DeterministicSpec[name] | SemanticSpec[name])


def test_semantic_decoded_with_defaults() -> None:
    spec = decode(SEMANTIC)
    assert isinstance(spec, SemanticSpec)
    assert (spec.tier, spec.bound, spec.version, spec.depends, spec.fallback, spec.timeout) == (
        Tier.MEDIUM,
        Bound.IO,
        1,
        (),
        None,
        None,
    )


def test_deterministic_decoded_with_every_field() -> None:
    raw = {
        **DETERMINISTIC,
        "depends": ["EXT-total-amount"],
        "fallback": "EXT-line-guess",
        "wiki": ["net-amount"],
        "bound": "cpu",
        "timeout": "PT30S",
        "version": 3,
    }
    spec = decode(raw)
    assert isinstance(spec, DeterministicSpec)
    assert (spec.bound, spec.timeout, spec.version, spec.wiki) == (Bound.CPU, timedelta(seconds=30), 3, ("net-amount",))


@pytest.mark.parametrize(
    ("change", "error"),
    [
        ({"name": "INF-total"}, "matching regex '^EXT-"),
        ({"name": "EXT-Total"}, "matching regex"),
        ({"name": "EXT-total--amount"}, "matching regex"),
        ({"depends": ["CLS-kind"]}, "at `$.depends[0]`"),
        ({"fallback": "total"}, "at `$.fallback`"),
        ({"wiki": ["Net Amount"]}, "at `$.wiki[0]`"),
        ({"description": "   "}, "at `$.description`"),
        ({"instructions": ""}, "at `$.instructions`"),
        ({"version": 0}, "at `$.version`"),
        ({"bound": "gpu"}, "at `$.bound`"),
        ({"tier": "ultra"}, "at `$.tier`"),
        ({"typo": 1}, "unknown field `typo`"),
        ({"kind": "magic"}, "Invalid value 'magic'"),
        ({"depends": ["EXT-total-amount"]}, "a spec cannot depend on itself"),
        ({"depends": ["EXT-a", "EXT-a"]}, "depends repeats a spec"),
        ({"fallback": "EXT-total-amount"}, "a spec cannot be its own fallback"),
        ({"depends": ["EXT-a"], "fallback": "EXT-a"}, "the fallback cannot also be a dependency"),
        ({"wiki": ["net", "net"]}, "wiki repeats a term"),
        ({"output": {"type": "array"}}, 'needs an object root: {"type": "object", ...} - at `$.output`'),
        (
            {"output": {"type": "object", "minProperties": "x"}},
            "no valid JSON Schema: it breaks the meta-schema - at `$.output`",
        ),
        ({"examples": [{"total": 1}, {"total": "x"}]}, "examples [1] do not match output"),
    ],
)
def test_one_document_validated_while_decoding(change: dict[str, Any], error: str) -> None:
    with pytest.raises(msgspec.ValidationError) as caught:
        decode({**SEMANTIC, **change})
    assert error in str(caught.value)


def test_deterministic_refuses_semantic_fields() -> None:
    with pytest.raises(msgspec.ValidationError, match="unknown field `instructions`"):
        decode({**DETERMINISTIC, "instructions": "x"})


@pytest.mark.parametrize("section", list(Section))
def test_name_type_is_the_sections_own(section: Section) -> None:
    raw = {**DETERMINISTIC, "name": f"{PREFIXES[section]}-line-sum"}
    assert decode(raw, section).name == raw["name"]
    assert Spec.named(section) is Spec.named(section)


def test_kinds_have_their_slots() -> None:
    assert DeterministicSpec.SLOTS == (Slot.RUNNER, Slot.CHECK)
    assert SemanticSpec.SLOTS == (Slot.PRE, Slot.POST, Slot.CHECK)


def test_plugs_are_the_slots_filled() -> None:
    spec = decode({**DETERMINISTIC, "check": "agnostic/context/present", "args": {"check": {"needs": []}}})
    assert spec.plugs == {Slot.RUNNER: "owned/linesum", Slot.CHECK: "agnostic/context/present"}
    assert decode(SEMANTIC).plugs == {}
    assert decode({**SEMANTIC, "post": "agnostic/number/scale"}).plugs == {Slot.POST: "agnostic/number/scale"}


@pytest.mark.parametrize(
    ("raw", "error"),
    [
        ({**SEMANTIC, "runner": "owned/x"}, "unknown field `runner`"),
        ({**DETERMINISTIC, "pre": "owned/x"}, "unknown field `pre`"),
        ({**DETERMINISTIC, "post": "owned/x"}, "unknown field `post`"),
        ({k: v for k, v in DETERMINISTIC.items() if k != "runner"}, "missing required field `runner`"),
        ({**DETERMINISTIC, "runner": "owned/line_sum"}, "at `$.runner`"),
        ({**DETERMINISTIC, "check": "agnostic/present"}, "at `$.check`"),
        ({**SEMANTIC, "pre": "tools/pages"}, "at `$.pre`"),
        ({**SEMANTIC, "args": {"pre": {}}}, "args name slots it does not plug: ['pre']"),
        ({**DETERMINISTIC, "args": {"post": {}}}, "args name slots it does not plug: ['post']"),
    ],
    ids=[
        "runner-on-semantic",
        "pre-on-deterministic",
        "post-on-deterministic",
        "runner-missing",
        "ref-two-words",
        "ref-agnostic-without-capability",
        "ref-unscoped",
        "args-unplugged",
        "args-foreign-slot",
    ],
)
def test_slots_are_rigid_per_kind(raw: dict[str, Any], error: str) -> None:
    with pytest.raises(msgspec.ValidationError) as caught:
        decode(raw)
    assert error in str(caught.value)


def test_a_pipeline_extends_a_spec_with_its_own_kind() -> None:
    class TableSpec[N: str](SemanticSpec[N], frozen=True, kw_only=True, tag="table"):
        columns: tuple[str, ...]

    name = Spec.named(Section.EXTRACT)
    spec = CheckedStruct.convert(
        {**SEMANTIC, "kind": "table", "columns": ["sku"]}, SemanticSpec[name] | TableSpec[name]
    )
    assert isinstance(spec, TableSpec)
    assert (spec.columns, spec.tier) == (("sku",), Tier.MEDIUM)


def test_an_extension_cannot_reshape_inherited_fields() -> None:
    with pytest.raises(TypeError, match=r"redefines inherited spec fields \['instructions', 'output'\]"):

        class Broken[N: str](SemanticSpec[N], frozen=True, kw_only=True, tag="broken"):
            output: JsonSchema
            instructions: int


def test_a_runner_knows_its_scope() -> None:
    owned = Runner(ref="owned/linesum", role=Role.RUN, file="x.py", doc="Sum.")
    tool = Runner(ref="agnostic/number/scale", role=Role.POST, file="y.py", doc="Scale.")
    assert (owned.scope, tool.scope) == (Scope.OWNED, Scope.AGNOSTIC)


##### BUILT IN CODE — the same validation as decoding, never skipped #####
def test_built_in_code_holds_checked_values() -> None:
    ### plain values on purpose: what a caller without the checked types would pass.
    fields: dict[str, Any] = {
        "name": "EXT-total",
        "description": "d",
        "instructions": "x",
        "output": {"type": "object"},
    }
    spec = SemanticSpec(**fields)
    assert isinstance(spec.output, JsonSchema)
    assert spec.output.validator.is_valid({})


@pytest.mark.parametrize(
    ("fields", "error"),
    [
        ({"output": {"type": "array"}}, "a JSON Schema needs an object root"),
        ({"name": "XYZ-total"}, "matching regex '^(?:ING|NOR|CLS|EXT|VAL|ENR|INF|AUD|TRF|REP|CUS)-"),
        ({"version": 0}, "Expected `int` >= 1 - at `$.version`"),
        ({"depends": ["EXT-total"]}, "a spec cannot depend on itself"),
        (
            {"examples": ({"total": 1},), "output": {"type": "object", "properties": {"total": {"type": "string"}}}},
            "examples [0] do not match output",
        ),
    ],
)
def test_built_in_code_validated_like_decoded(fields: dict[str, Any], error: str) -> None:
    base: dict[str, Any] = {"name": "EXT-total", "description": "d", "instructions": "x", "output": {"type": "object"}}
    with pytest.raises(msgspec.ValidationError) as caught:
        SemanticSpec(**{**base, **fields})
    assert error in str(caught.value)


def test_a_raw_dict_never_decodes_without_the_hook() -> None:
    with pytest.raises(msgspec.ValidationError, match="Expected `JsonSchema`, got `dict`"):
        msgspec.convert(SEMANTIC, SemanticSpec[NAME])
