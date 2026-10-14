"""tests/integration/e_tui/interact/registry: the table maps every spec kind to its object; a gap fails loud."""

import msgspec
import pytest

from e_tui.interact.choice import Choice
from e_tui.interact.confirm import Confirm
from e_tui.interact.input import TextInput
from e_tui.interact.registry import build
from e_tui.interact.report import Report
from e_tui.interact.toggle import Toggle
from e_tui.models.error import InteractError
from e_tui.models.object import ChoiceSpec, ConfirmSpec, InputSpec, ReportSpec, Spec, ToggleSpec


class Odd(msgspec.Struct, frozen=True, tag="odd", tag_field="kind"):
    """A spec the table never learned."""


@pytest.mark.parametrize(
    ("spec", "cls"),
    [
        (ToggleSpec(), Toggle),
        (ChoiceSpec(), Choice),
        (InputSpec(), TextInput),
        (ConfirmSpec(), Confirm),
        (ReportSpec(), Report),
    ],
    ids=["toggle", "choice", "input", "confirm", "report"],
)
async def test_registry_builds_the_object_for_each_kind(spec: Spec, cls: type) -> None:
    assert isinstance(build(spec), cls)


async def test_registry_refuses_an_unmapped_spec() -> None:
    with pytest.raises(InteractError, match="no interactive object"):
        build(Odd())
