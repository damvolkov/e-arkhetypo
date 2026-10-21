"""e_tui.interact.choice: pick exactly one — the api-selector, the model-picker.

A `RadioSet` built from the spec's fields, `selected` (or the committed `previous` on a revisit) lit
from the start. Nothing commits until a button answers: an unanswered choice is `None`, the signal the
viewer uses to keep the step's accept disabled."""

from collections.abc import Sequence

from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import Label, RadioButton, RadioSet

from e_tui.models.object import ChoiceSpec, Commit


class Choice(Vertical):
    """One radio per field; `commit` reports the single chosen key, or None until one answers."""

    def __init__(self, spec: ChoiceSpec, previous: Sequence[str] = ()) -> None:
        picked = next(iter(previous), spec.selected)
        self._buttons = {
            field.key: RadioButton(field.label, value=field.key == picked, id=field.key) for field in spec.fields
        }
        super().__init__(*self._headed(spec.prompt, [RadioSet(*self._buttons.values())]))

    ############################################################

    def commit(self) -> Commit | None:
        """The chosen key as a one-tuple — or None while nothing is lit."""
        chosen = tuple(key for key, button in self._buttons.items() if button.value)
        return Commit(values=chosen) if chosen else None

    ##### PRIVATE #####

    @staticmethod
    def _headed(prompt: str, rows: Sequence[Widget]) -> list[Widget]:
        """The optional prompt above the choices."""
        return [Label(prompt), *rows] if prompt else list(rows)
