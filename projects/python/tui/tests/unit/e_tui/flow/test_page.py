"""tests/unit/e_tui/flow/page: a page is a frozen record — identity, interaction, dependencies and wiring."""

from typing import Any

from e_tui.flow.page import Page
from e_tui.models.object import ConfirmSpec


def _page(**over: Any) -> Page:
    base: dict[str, Any] = {"id": "a", "title": "A", "spec": ConfirmSpec()}
    return Page(**{**base, **over})


def test_page_defaults_declare_no_dependency_or_wiring() -> None:
    page = _page()
    assert page.next is None
    assert page.route is None
    assert page.condition is None
    assert page.on_commit is None
    assert page.requires == frozenset()
    assert page.produces == frozenset()
    assert dict(page.meta) == {}


def test_page_carries_static_and_conditional_wiring() -> None:
    route = lambda commit, state: "b"  # noqa: E731 — a tiny conditional edge for the record
    page = _page(next="z", route=route, meta={"note": "hi"})
    assert page.next == "z"
    assert page.route is route
    assert page.meta["note"] == "hi"


def test_page_declares_its_dependency_contract() -> None:
    gate = lambda state: True  # noqa: E731 — a trivial placement condition
    write = lambda commit, state: None  # noqa: E731 — a trivial domain hook
    page = _page(requires=frozenset({"system"}), produces=frozenset({"choice"}), condition=gate, on_commit=write)
    assert page.requires == frozenset({"system"})
    assert page.produces == frozenset({"choice"})
    assert page.condition is gate
    assert page.on_commit is write
