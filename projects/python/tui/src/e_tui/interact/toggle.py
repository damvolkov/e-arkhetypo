"""e_tui.interact.toggle: many on/off switches — the module-picker of the house flows.

One row per `Field`: a label and a `Switch`. A field in `locked` cannot be turned off (e-taxis'
"required"); a field in `defaults` starts on, unless the walk is revisiting and `previous` overrides
the defaults with what the user already committed. Committing is always possible — an empty toggle is
a legitimate answer (the user switched everything off)."""

from collections.abc import Sequence

from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Label, Switch

from e_tui.models.object import Commit, Field, ToggleSpec


class Toggle(Vertical):
    """A column of switch rows wired from a `ToggleSpec`; `commit` reports the keys left on."""

    def __init__(self, spec: ToggleSpec, previous: Sequence[str] = ()) -> None:
        on = frozenset(previous or spec.defaults)
        self._switches = {field.key: self._dial(field, on, spec.locked) for field in spec.fields}
        rows = [
            Horizontal(Label(f"{field.label}  {field.detail}".rstrip(), expand=False), self._switches[field.key])
            for field in spec.fields
        ]
        super().__init__(*self._headed(spec.prompt, rows))

    ############################################################

    def commit(self) -> Commit | None:
        """Every key whose switch is on — empty when the user cleared them all."""
        return Commit(values=tuple(key for key, switch in self._switches.items() if switch.value))

    ##### PRIVATE #####

    @staticmethod
    def _dial(field: Field, on: frozenset[str], locked: Sequence[str]) -> Switch:
        """One switch, keyed by its field so it is addressable: locked fields are required-on and dead to the hand."""
        return Switch(value=field.key in on or field.key in locked, disabled=field.key in locked, id=field.key)

    @staticmethod
    def _headed(prompt: str, rows: Sequence[Widget]) -> list[Widget]:
        """The optional prompt above the rows."""
        return [Label(prompt), *rows] if prompt else list(rows)
