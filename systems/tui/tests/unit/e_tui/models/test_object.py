"""tests/unit/e_tui/models/object: the specs are tagged unions — one kind field picks the struct."""

import msgspec

from e_tui.models.object import (
    ChoiceSpec,
    Commit,
    ConfirmSpec,
    Field,
    InputSpec,
    ReportSpec,
    Spec,
    ToggleSpec,
)

##### KIND → STRUCT #####
KINDS = {"toggle": ToggleSpec, "choice": ChoiceSpec, "input": InputSpec, "confirm": ConfirmSpec, "report": ReportSpec}


def test_commit_defaults_to_an_accepted_empty_answer() -> None:
    answer = Commit()
    assert answer.values == ()
    assert answer.ok


def test_field_detail_is_optional() -> None:
    assert Field(key="k", label="L").detail == ""


def test_spec_union_decodes_from_a_discriminated_mapping() -> None:
    decoded = msgspec.convert({"kind": "toggle", "prompt": "p", "fields": [{"key": "a", "label": "A"}]}, Spec)
    assert isinstance(decoded, ToggleSpec)
    assert decoded.fields[0].key == "a"


def test_spec_union_resolves_every_kind() -> None:
    decoded = {kind: msgspec.convert({"kind": kind}, Spec) for kind in KINDS}
    assert all(isinstance(decoded[kind], cls) for kind, cls in KINDS.items())
