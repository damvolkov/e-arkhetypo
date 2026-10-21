"""e_tui.flow.walk: the client that navigates a graph — advance, reverse, reset, all typed.

The walker is the only thing that mutates a `FlowState`, and every one of its moves answers with a value from
the `Move` sum, never an exception: `OnPage` (a page to render), `Finished` (past the last), `Declined` (the
user said no), `AtFirst` (nowhere left to reverse). That is what lets the TUI be a dumb viewer — it matches
the sum and shows a widget; all the routing lives here. Advancing fires the page's `on_commit` (its domain
data, written before any route reads it); placement `condition`s are *not* re-checked — they were settled when
the graph was built, so a walk onto a structurally bad page cannot happen. The reverse keeps committed answers
so a revisited page re-shows them; only `reset` wipes the walk."""

from dataclasses import dataclass

from e_tui.flow.graph import Graph
from e_tui.flow.page import Page
from e_tui.flow.state import FlowState
from e_tui.models.object import Commit

##### MOVES #####


@dataclass(frozen=True, slots=True)
class OnPage:
    """A page is now on screen."""

    page: Page
    revisited: bool


@dataclass(frozen=True, slots=True)
class Declined:
    """The user refused the current page; the walk stays put."""


@dataclass(frozen=True, slots=True)
class AtFirst:
    """Already at the head of the trail — reverse has nowhere to go."""


@dataclass(frozen=True, slots=True)
class Finished:
    """The walk ran off the end of the graph."""


Move = OnPage | Declined | AtFirst | Finished


class Walker:
    """Navigates `graph`: holds the shared `FlowState`, answers every move with a typed result."""

    def __init__(self, graph: Graph) -> None:
        self.state = FlowState(graph)

    ############################################################

    ##### PUBLIC #####

    def here(self) -> Page:
        """The page under the cursor — what the viewer must render right now."""
        return self.state.here

    def advance(self, commit: Commit) -> Move:
        """Record the answer, derive the page's domain data, then follow its route (or its static successor)."""
        if not commit.ok:
            return Declined()
        page = self.state.here
        self.state.answers[self.state.at] = commit.values
        if page.on_commit is not None:
            page.on_commit(commit, self.state.data)
        lead = self.state.graph.next_of(page, commit, self.state.data)
        return self._enter(lead) if lead else Finished()

    def back(self) -> Move:
        """Reverse one page, restoring the trail — answers stay so the revisit re-shows them."""
        if not self.state.trail:
            return AtFirst()
        *rest, target = self.state.trail
        self.state.trail = tuple(rest)
        self.state.at = target
        return OnPage(self.state.here, revisited=True)

    def reset(self) -> Move:
        """Wipe the walk: fresh data, empty trail, back to the entry page."""
        self.state.trail = ()
        self.state.at = self.state.graph.entry.id
        self.state.data.answers.clear()
        return OnPage(self.state.here, revisited=False)

    ##### PRIVATE #####

    def _enter(self, target: str) -> Move:
        """Move the cursor to `target`, pushing the page left behind onto the trail."""
        self.state.trail = (*self.state.trail, self.state.at)
        self.state.at = target
        return OnPage(self.state.here, revisited=target in self.state.trail)
