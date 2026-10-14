"""tests/unit/e_tui/flow/graph: building a graph is where a bad flow dies — before anyone walks it."""

from typing import Any

import pytest

from e_tui.flow.graph import Graph
from e_tui.flow.page import Page
from e_tui.models.error import FlowError
from e_tui.models.object import Commit, ConfirmSpec

##### BUILDERS #####


def _page(page_id: str, **over: Any) -> Page:
    base: dict[str, Any] = {"id": page_id, "title": page_id.upper(), "spec": ConfirmSpec()}
    return Page(**{**base, **over})


def _graph(*pages: Page) -> Graph:
    return Graph("g", pages)


##### VALIDATION #####


def test_graph_rejects_an_empty_flow() -> None:
    with pytest.raises(FlowError, match="at least one page"):
        _graph()


def test_graph_rejects_repeated_page_ids() -> None:
    with pytest.raises(FlowError, match="repeated page id"):
        _graph(_page("a"), _page("a"))


def test_graph_rejects_a_dangling_static_successor() -> None:
    with pytest.raises(FlowError, match="leads to unknown"):
        _graph(_page("a", next="ghost"))


def test_graph_accepts_a_route_to_a_name_it_does_not_declare() -> None:
    flow = _graph(_page("a", route=lambda c, s: "later"), _page("later"))
    assert flow.entry.id == "a"


##### VIEWS #####


def test_graph_entry_is_the_head_of_the_line() -> None:
    assert _graph(_page("a"), _page("b")).entry.id == "a"


def test_graph_page_returns_the_named_page() -> None:
    assert _graph(_page("a"), _page("b")).page("b").id == "b"


def test_graph_page_refuses_an_unknown_name() -> None:
    with pytest.raises(FlowError, match="no page 'z'"):
        _graph(_page("a")).page("z")


def test_graph_follows_resolves_declaration_order_and_the_end() -> None:
    flow = _graph(_page("a"), _page("b"))
    assert flow.follows(flow.page("a")) == "b"
    assert flow.follows(flow.page("b")) is None


def test_graph_next_of_prefers_the_declared_next_over_order() -> None:
    flow = _graph(_page("a", next="c"), _page("b"), _page("c"))
    assert flow.next_of(flow.page("a"), Commit(), {}) == "c"
    assert flow.next_of(flow.page("b"), Commit(), {}) == "c"


def test_graph_next_of_lets_a_route_decide_alone() -> None:
    flow = _graph(_page("a", next="b", route=lambda c, s: "c"), _page("b"), _page("c"))
    assert flow.next_of(flow.page("a"), Commit(), {}) == "c"
