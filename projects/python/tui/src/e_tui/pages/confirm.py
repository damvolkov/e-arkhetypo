"""e_tui.pages.confirm: the fork with a consequence — accepting advances the walk; declining keeps it put."""

from typing import TYPE_CHECKING

from e_tui.flow.page import Page
from e_tui.models.object import ConfirmSpec

if TYPE_CHECKING:
    from collections.abc import MutableMapping

    from e_tui.models.object import Commit


def _record(commit: Commit, state: MutableMapping[str, object]) -> None:
    """A yes that reaches this page means the plan will materialize."""
    state["materialized"] = commit.ok


PAGE = Page(
    id="confirm",
    title="Confirm",
    spec=ConfirmSpec(prompt="materialize?", detail="this writes the project tree"),
    on_commit=_record,
    next="report",
)
