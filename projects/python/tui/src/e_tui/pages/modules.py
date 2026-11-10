"""e_tui.pages.modules: pick the stack modules — the dependency lesson in one page.

It `requires` `system` and carries a placement `condition`: registering it before the system page would die
at the `add`, because nothing before it produces what its condition reads."""

from typing import TYPE_CHECKING, Final

from e_tui.flow.page import Page
from e_tui.flow.state import has
from e_tui.models.object import Field, ToggleSpec

if TYPE_CHECKING:
    from e_tui.infra.state import State
    from e_tui.models.object import Commit

##### FIELDS #####
MODULES: Final = (
    Field(key="rdb", label="Postgres"),
    Field(key="vdb", label="Qdrant"),
    Field(key="speech", label="Speech"),
)


##### LOGIC #####


def _record(commit: Commit, state: State) -> None:
    """Park the switched-on keys as the shared `modules`."""
    state["modules"] = commit.values


PAGE: Final = Page(
    id="modules",
    title="Modules",
    spec=ToggleSpec(prompt="stack modules", fields=MODULES),
    requires=frozenset({"system"}),
    condition=lambda state: has(state, "system"),
    on_commit=_record,
    next="confirm",
)
