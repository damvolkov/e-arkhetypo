"""e_tui.interact.input: one line of text — names, paths, a secret.

An `Input` with the spec's placeholder, `secret` masking it as a password. Empty never commits: the
viewer keeps the accept dark until there is a string, so a required line cannot be skipped by
accident. A revisit re-shows what was typed."""

from collections.abc import Sequence

from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import Input, Label

from e_tui.models.object import Commit, InputSpec


class TextInput(Vertical):
    """A prompt over a single-line input; `commit` reports the text, or None while it is blank."""

    def __init__(self, spec: InputSpec, previous: Sequence[str] = ()) -> None:
        self._input = Input(value=next(iter(previous), "") or None, placeholder=spec.placeholder, password=spec.secret)
        super().__init__(*self._headed(spec.prompt, [self._input]))

    ############################################################

    def commit(self) -> Commit | None:
        """The typed text trimmed — or None while the line is empty."""
        text = self._input.value.strip()
        return Commit(values=(text,)) if text else None

    ##### PRIVATE #####

    @staticmethod
    def _headed(prompt: str, rows: Sequence[Widget]) -> list[Widget]:
        """The optional prompt above the field."""
        return [Label(prompt), *rows] if prompt else list(rows)
