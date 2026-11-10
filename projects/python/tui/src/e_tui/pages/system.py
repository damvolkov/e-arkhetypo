"""e_tui.pages.system: pick the target system — the flow's entry, the source of the shared `system`.

Produces `system`; forks an `api` pick through a dsn line, so this page also shows the conditional edge."""

from typing import TYPE_CHECKING, Final

from e_tui.flow.page import Page
from e_tui.models.object import ChoiceSpec, Field

if TYPE_CHECKING:
    from e_tui.infra.state import State
    from e_tui.models.object import Commit

##### FIELDS #####
SYSTEMS: Final = (
    Field(key="api", label="API service"),
    Field(key="cli", label="CLI tool"),
    Field(key="tui", label="TUI app"),
)


##### LOGIC #####


def _record(commit: Commit, state: State) -> None:
    """Park the chosen key as the shared `system`."""
    state["system"] = next(iter(commit.values), None)


def _fork(commit: Commit, _state: State) -> str | None:
    """An api pick detours through the dsn line; anything else goes straight to the modules."""
    return "db" if "api" in commit.values else "modules"


PAGE: Final = Page(
    id="system",
    title="System",
    spec=ChoiceSpec(prompt="which system?", fields=SYSTEMS),
    produces=frozenset({"system"}),
    on_commit=_record,
    route=_fork,
)
