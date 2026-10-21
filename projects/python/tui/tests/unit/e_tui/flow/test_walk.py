"""tests/unit/e_tui/flow/walk: the client navigates — advance, route, commit-hook, decline, reverse, reset, all typed."""

from collections.abc import Mapping, MutableMapping

import pytest

from e_tui.flow.graph import Graph
from e_tui.flow.page import Page
from e_tui.flow.walk import AtFirst, Declined, Finished, OnPage, Walker
from e_tui.models.error import FlowError
from e_tui.models.object import Commit, ConfirmSpec


def _fork(commit: Commit, state: Mapping[str, object]) -> str | None:
    return "yes" if "go" in commit.values else "no"


def _flow() -> Graph:
    return Graph(
        "g",
        (
            Page("ask", "Ask", ConfirmSpec()),
            Page("yes", "Yes", ConfirmSpec()),
            Page("no", "No", ConfirmSpec()),
        ),
    )


def _routed() -> Graph:
    return Graph(
        "g",
        (
            Page("ask", "Ask", ConfirmSpec(), route=_fork),
            Page("yes", "Y", ConfirmSpec()),
            Page("no", "N", ConfirmSpec()),
        ),
    )


def test_walker_starts_at_the_entry_page() -> None:
    assert Walker(_flow()).here().id == "ask"


def test_advance_onto_the_next_static_page() -> None:
    walk = Walker(_flow())
    move = walk.advance(Commit())
    assert isinstance(move, OnPage)
    assert move.page.id == "yes"
    assert not move.revisited


def test_declined_commit_does_not_move_the_walk() -> None:
    walk = Walker(_flow())
    assert isinstance(walk.advance(Commit(ok=False)), Declined)
    assert walk.here().id == "ask"


def test_advance_past_the_end_finishes_the_walk() -> None:
    walk = Walker(_flow())
    walk.advance(Commit())  # ask -> yes
    walk.advance(Commit())  # yes -> no
    assert isinstance(walk.advance(Commit()), Finished)  # no has no successor


def test_route_decides_where_advance_lands() -> None:
    walk = Walker(_routed())
    walk.advance(Commit(values=("skip",)))  # route sends it to "no"
    assert walk.here().id == "no"


def test_on_commit_writes_domain_data_before_the_route_reads_it() -> None:
    def write(commit: Commit, state: MutableMapping[str, object]) -> None:
        state["system"] = commit.values[0]

    def route(commit: Commit, state: Mapping[str, object]) -> str | None:
        return "api" if state.get("system") == "api" else "cli"

    graph = Graph(
        "g",
        (
            Page("ask", "Ask", ConfirmSpec(), on_commit=write, route=route),
            Page("api", "A", ConfirmSpec()),
            Page("cli", "C", ConfirmSpec()),
        ),
    )
    walk = Walker(graph)
    walk.advance(Commit(values=("api",)))
    assert walk.here().id == "api"
    assert walk.state.data["system"] == "api"


def test_reverse_restores_the_previous_page_as_revisited() -> None:
    walk = Walker(_flow())
    walk.advance(Commit())
    move = walk.back()
    assert isinstance(move, OnPage)
    assert move.page.id == "ask"
    assert move.revisited


def test_reverse_at_the_head_reports_at_first() -> None:
    assert isinstance(Walker(_flow()).back(), AtFirst)


def test_committed_answers_survive_a_reverse_for_the_revisit() -> None:
    walk = Walker(_routed())
    walk.advance(Commit(values=("keep",)))  # route: no "go" -> "no"
    walk.back()
    assert walk.state.values_for("ask") == ("keep",)


def test_reset_wipes_trail_position_and_answers() -> None:
    walk = Walker(_flow())
    walk.advance(Commit(values=("x",)))
    move = walk.reset()
    assert isinstance(move, OnPage)
    assert walk.here().id == "ask"
    assert walk.state.values_for("ask") == ()


def test_advance_to_a_route_naming_an_unknown_page_raises_through_here() -> None:
    walk = Walker(Graph("g", (Page("a", "A", ConfirmSpec(), route=lambda c, s: "ghost"),)))
    with pytest.raises(FlowError):
        walk.advance(Commit())
