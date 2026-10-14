"""e_tui.interact.confirm: a fork with a consequence — do it, or back out.

Two buttons, yes and no. Nothing commits until one is pressed; `no` answers `ok=False`, which the
walker turns into a `Declined` (the walk stays put, the step can be re-answered), while `yes` lets the
step's route decide where the fork leads. The `detail` line is where the "this deletes X" warning goes."""

from collections.abc import Sequence

from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Label, Static

from e_tui.models.object import Commit, ConfirmSpec

##### LABELS #####
YES: str = "yes"
NO: str = "no"


class Confirm(Vertical):
    """A prompt and a yes/no pair; `commit` reports the fork taken, or None until one is pressed."""

    def __init__(self, spec: ConfirmSpec, _previous: Sequence[str] = ()) -> None:
        self._answer: bool | None = None
        body = [Static(spec.detail)] if spec.detail else []
        super().__init__(
            *([Label(spec.prompt)] if spec.prompt else []),
            *body,
            Horizontal(Button(YES, id=YES, variant="success"), Button(NO, id=NO, variant="error")),
        )

    ############################################################

    def commit(self) -> Commit | None:
        """The taken fork — or None while neither button has answered."""
        return Commit(ok=self._answer) if self._answer is not None else None

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Latch the answer from the button id; the viewer reads it through `commit`."""
        self._answer = event.button.id == YES
