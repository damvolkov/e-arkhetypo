"""e_tui.pages.db: the api-only detour — a connection string, skipped by every non-api pick."""

from typing import TYPE_CHECKING

from e_tui.flow.page import Page
from e_tui.models.object import InputSpec

if TYPE_CHECKING:
    from collections.abc import MutableMapping

    from e_tui.models.object import Commit


def _record(commit: Commit, state: MutableMapping[str, object]) -> None:
    """Park the typed connection string as the shared `dsn`."""
    state["dsn"] = next(iter(commit.values), "")


PAGE = Page(
    id="db",
    title="Data source",
    spec=InputSpec(prompt="connection string?", placeholder="postgres://..."),
    produces=frozenset({"dsn"}),
    on_commit=_record,
    next="modules",
)
