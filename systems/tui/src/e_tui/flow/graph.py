"""e_tui.flow.graph: the walkable shape — pages wired into one sequential flow with conditional edges.

The house flow is a sequence with forks: pages declared in order, each leading by `next` or by its
conditional `route`, every move reversible. Building the graph is the moment where lies become visible — an
unknown successor, a repeated id, an empty flow — so a `FlowError` surfaces at construction, never mid-walk.
Storage is a frozen adjacency mapping: the graph is data, the navigation lives in `e_tui.flow.walk`; no
third-party graph engine earns its keep at these sizes (O(1) by dict, full stop — revisit under real load,
not before it). The flow that carries dependency-declaration and placement-validation is `e_tui.flow.pages`,
which builds this shape one page at a time."""

from collections.abc import Mapping
from dataclasses import dataclass

from e_tui.flow.page import Page
from e_tui.models.error import FlowError
from e_tui.models.object import Commit


@dataclass(frozen=True, slots=True)
class Graph:
    """A flow: ordered pages, a derived index, and the entry point at the head of the line."""

    id: str
    pages: tuple[Page, ...]

    def __post_init__(self) -> None:
        """Refuse an unwalkable flow before anyone tries to walk it."""
        bad = f"graph {self.id!r}: a flow needs at least one page"
        _check(bool(self.pages), bad)
        seen = [page.id for page in self.pages]
        dupes = f"graph {self.id!r}: repeated page id"
        _check(len(set(seen)) == len(seen), dupes)
        for page in self.pages:
            dangling = f"graph {self.id!r}: page {page.id!r} leads to unknown {page.next!r}"
            _check(page.next is None or page.next in seen, dangling)

    ##### VIEWS #####

    @property
    def entry(self) -> Page:
        """The first declared page — where every walk begins."""
        return self.pages[0]

    def page(self, target: str) -> Page:
        """The named page: a walk onto an unknown id surfaces as `FlowError`, typed."""
        try:
            return {page.id: page for page in self.pages}[target]
        except KeyError as error:
            missing = f"graph {self.id!r}: no page {target!r}"
            raise FlowError(missing) from error

    def follows(self, origin: Page) -> str | None:
        """The static successor of `origin` in declaration order (`None` past the line's end)."""
        index = self._order()[origin.id]
        return self.pages[index + 1].id if index + 1 < len(self.pages) else None

    def next_of(self, page: Page, commit: Commit, state: Mapping[str, object]) -> str | None:
        """Where the walk goes after `page`: its route decides alone; else its declared next; else the next in line."""
        return page.route(commit, state) if page.route else (page.next or self.follows(page))

    ##### PRIVATE #####

    def _order(self) -> Mapping[str, int]:
        """id → position, rebuilt in O(n) — graphs here are tens of pages, not thousands."""
        return {page.id: index for index, page in enumerate(self.pages)}


def _check(holds: bool, why: str) -> None:  # noqa: FBT001 — the boolean argument IS the predicate
    """Raise `FlowError(why)` when `holds` is false."""
    if not holds:
        raise FlowError(why)
