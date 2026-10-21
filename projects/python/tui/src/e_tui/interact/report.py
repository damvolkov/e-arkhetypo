"""e_tui.interact.report: a page to read — result, plan, error trail; advance-only.

The passive object: it renders the spec's lines and commits immediately (there is nothing to answer),
so the viewer's accept simply moves on. This is where a step shows what the walk has produced before
offering the next fork or the end."""

from collections.abc import Sequence

from textual.containers import Vertical
from textual.widgets import Label, Static

from e_tui.models.object import Commit, ReportSpec


class Report(Vertical):
    """A read-only block; `commit` is always the empty yes — the step exists to be seen, then passed."""

    def __init__(self, spec: ReportSpec, _previous: Sequence[str] = ()) -> None:
        super().__init__(
            *([Label(spec.prompt)] if spec.prompt else []),
            Static("\n".join(spec.lines)),
        )

    def commit(self) -> Commit | None:
        """Instantly accepted: a report has no answer, only a next."""
        return Commit()
