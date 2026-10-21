"""e_tui.interact.registry: the frozen table that turns a spec into the object that shows it.

One lookup, keyed by the spec's type — the whole dispatch of the interactive layer. A new kind is a new
row here and a new module, never a new branch in the viewer; an unmapped spec raises `InteractError` at
build time, so a gap shows up the moment a flow names a kind the template cannot render. The mapped
makers are the `ObjectPort` protocol's five witnesses."""

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Final

from e_tui.interact.choice import Choice
from e_tui.interact.confirm import Confirm
from e_tui.interact.input import TextInput
from e_tui.interact.ports import Maker, ObjectPort
from e_tui.interact.report import Report
from e_tui.interact.toggle import Toggle
from e_tui.models.error import InteractError
from e_tui.models.object import (
    ChoiceSpec,
    ConfirmSpec,
    InputSpec,
    ReportSpec,
    ToggleSpec,
)

##### TABLE #####
MAKERS: Final[Mapping[type[object], Maker]] = MappingProxyType(
    {
        ToggleSpec: Toggle,
        ChoiceSpec: Choice,
        InputSpec: TextInput,
        ConfirmSpec: Confirm,
        ReportSpec: Report,
    }
)


def build(spec: object, previous: Sequence[str] = ()) -> ObjectPort:
    """The object for `spec`, restored to `previous` values — or `InteractError` for an unmapped kind."""
    try:
        return MAKERS[type(spec)](spec, previous)
    except KeyError as error:
        gap = f"no interactive object is registered for {type(spec).__name__}"
        raise InteractError(gap) from error
