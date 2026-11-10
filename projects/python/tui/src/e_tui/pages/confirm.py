"""e_tui.pages.confirm: the fork with a consequence — accepting advances the walk; declining keeps it put."""

from typing import TYPE_CHECKING, Final

from e_tui.flow.page import Page
from e_tui.models.object import ConfirmSpec

if TYPE_CHECKING:
    from e_tui.infra.state import State
    from e_tui.models.object import Commit


def _record(commit: Commit, state: State) -> None:
    """A yes that reaches this page means the plan will materialize."""
    state["materialized"] = commit.ok


PAGE: Final = Page(
    id="confirm",
    title="Confirm",
    spec=ConfirmSpec(prompt="materialize?", detail="this writes the project tree"),
    on_commit=_record,
    next="report",
)
