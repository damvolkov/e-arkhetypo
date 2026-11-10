"""e_tui.demo: the reusable fake app — pages folded into a validated flow that emits a data model.

This is the host the template exists for, in miniature: every page lives in `e_tui.pages`, imported here and
added through `PagesBuilder` in list order (the declarative, mount-ordered incorporation), the answers pile up
in the shared `State`, and a `result` view resolves them into an `AppBlueprint` the instant the walk finishes.
Copy this module and the `pages/` package to start a real app — nothing here is wired into the framework.
"""

from functools import reduce
from typing import TYPE_CHECKING, Final

import eserde
import msgspec
from textual.widgets import Label, Static

from e_tui.app import WizardApp
from e_tui.flow.pages import PagesBuilder
from e_tui.pages import confirm, db, modules, report, system

if TYPE_CHECKING:
    from collections.abc import Iterable

    from textual.widget import Widget

    from e_tui.infra.state import State

##### MODEL #####


class AppBlueprint(msgspec.Struct, frozen=True, omit_defaults=True):
    """The data model the wizard spits out — every choice resolved into one typed record."""

    system: str | None = None
    dsn: str | None = None
    modules: tuple[str, ...] = ()
    materialized: bool = True


##### PAGES #####
PAGES: Final = (system.PAGE, db.PAGE, modules.PAGE, confirm.PAGE, report.PAGE)


##### RESULT #####


def _blueprint(state: State) -> AppBlueprint:
    """The shared state, converted into the model — the page hooks wrote these exact shapes; other keys are ignored."""
    return msgspec.convert(dict(state), AppBlueprint)


def _result_view(state: State) -> Iterable[Widget]:
    """The payoff: mount the emitted blueprint as formatted JSON once the walk is done."""
    model = msgspec.json.format(eserde.dumps(_blueprint(state))).decode()
    return [Label("project blueprint"), Static(model, markup=False)]  # the JSON's brackets are literal, not markup


def build() -> WizardApp:
    """Fold the pages in mount order — each validated at its `add` — and host the walk with its result view."""
    graph = reduce(lambda builder, page: builder.add(page), PAGES, PagesBuilder("wizard")).build()
    return WizardApp(graph, result=_result_view)
