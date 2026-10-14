"""tests/unit/e_tui/flow/pages: adding a page before its dependency is a structural lie — it dies at the add."""

import pytest

from e_tui.flow.page import Page
from e_tui.flow.pages import PagesBuilder
from e_tui.flow.state import has
from e_tui.models.error import PageStructureError
from e_tui.models.object import ChoiceSpec, ConfirmSpec, ToggleSpec


def _system() -> Page:
    return Page("system", "System", ChoiceSpec(), produces=frozenset({"system"}))


def _modules() -> Page:
    return Page("modules", "Modules", ToggleSpec(), requires=frozenset({"system"}))


def _terminal() -> Page:
    return Page("confirm", "Confirm", ConfirmSpec())


def test_add_seeds_produces_so_a_later_requirement_is_met() -> None:
    graph = PagesBuilder("w").add(_system()).add(_modules()).build()
    assert graph.entry.id == "system"
    assert [page.id for page in graph.pages] == ["system", "modules"]


def test_a_page_without_predecessors_needs_nothing_to_be_placed() -> None:
    assert PagesBuilder("w").add(_terminal()).build().entry.id == "confirm"


def test_a_requirement_no_predecessor_produces_is_rejected() -> None:
    with pytest.raises(PageStructureError, match="nothing before it produces"):
        PagesBuilder("w").add(_modules())


def test_a_condition_false_on_the_shadow_rejects_the_place() -> None:
    gated = Page("modules", "Modules", ToggleSpec(), condition=lambda state: has(state, "system"))
    with pytest.raises(PageStructureError, match="rejects its place"):
        PagesBuilder("w").add(gated)


def test_a_condition_true_on_the_produced_shadow_is_accepted() -> None:
    gated = Page("modules", "Modules", ToggleSpec(), condition=lambda state: has(state, "system"))
    assert PagesBuilder("w").add(_system()).add(gated).build().page("modules").id == "modules"


def test_a_repeated_page_id_is_rejected_at_the_add() -> None:
    with pytest.raises(PageStructureError, match="repeated page id"):
        PagesBuilder("w").add(_system()).add(_system())


def test_the_producer_can_read_its_own_output_on_a_later_page() -> None:
    builder = PagesBuilder("w").add(_system())
    graph = builder.add(_modules()).add(_terminal()).build()
    assert graph.page("confirm").id == "confirm"
