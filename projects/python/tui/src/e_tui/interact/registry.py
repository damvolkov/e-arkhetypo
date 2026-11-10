"""e_tui.interact.registry: the frozen table that turns a spec into the object that shows it.

One `match` on the spec's class — the whole dispatch of the interactive layer, typed end to end: each arm
hands its spec to the one widget that takes it, and `ObjectWidget` names the five that answer. A new kind is
a new arm here and a new module, never a new branch in the viewer; a spec outside the union raises
`InteractError` at build time, so a gap shows up the moment a flow names a kind the template cannot render.
The five widgets are the `ObjectPort` protocol's witnesses."""

from collections.abc import Sequence

from e_tui.interact.choice import Choice
from e_tui.interact.confirm import Confirm
from e_tui.interact.input import TextInput
from e_tui.interact.report import Report
from e_tui.interact.toggle import Toggle
from e_tui.models.error import InteractError
from e_tui.models.object import (
    ChoiceSpec,
    ConfirmSpec,
    InputSpec,
    ReportSpec,
    Spec,
    ToggleSpec,
)

##### TABLE #####
type ObjectWidget = Toggle | Choice | TextInput | Confirm | Report


def build(spec: Spec, previous: Sequence[str] = ()) -> ObjectWidget:
    """The object for `spec`, restored to `previous` values — or `InteractError` for a kind outside the union."""
    match spec:
        case ToggleSpec():
            return Toggle(spec, previous)
        case ChoiceSpec():
            return Choice(spec, previous)
        case InputSpec():
            return TextInput(spec, previous)
        case ConfirmSpec():
            return Confirm(spec, previous)
        case ReportSpec():
            return Report(spec, previous)
        case _:
            gap = f"no interactive object is registered for {type(spec).__name__}"
            raise InteractError(gap)
