"""e_tui.flow.pages: the builder that turns declared pages into a validated graph, one add at a time.

Pages are added dynamically and in mount order, so a page registered before the page that produces what it
reads is a structural lie — and it must die at the `add`, not mid-walk. The builder keeps a *shadow* `State`
seeded with a sentinel for every path already produced: at each `add` it checks the page's `requires` against
that shadow and runs its `condition` over it — presence and shape only, never a live value (values belong to
`route`) — then seeds the page's own `produces`. A breach raises `PageStructureError`; the graph that `build`
eventually emits is, by construction, walk-safe, so `e_tui.flow.walk` never re-checks a condition."""

from dataclasses import dataclass, field

from e_tui.flow.graph import Graph
from e_tui.flow.page import Page
from e_tui.flow.state import has, seed
from e_tui.models.error import PageStructureError
from infra.state import State

##### SHADOW #####
_PRESENCE: object = object()  # the sentinel a produced path holds in the shadow: presence, never a value


@dataclass(slots=True)
class PagesBuilder:
    """Accumulates pages in order, validating each against everything added before it."""

    id: str
    _pages: list[Page] = field(default_factory=list)
    _shadow: State = field(default_factory=State)

    ############################################################

    ##### PUBLIC #####

    def add(self, page: Page) -> "PagesBuilder":
        """Place `page` next: it dies if its id repeats, or a dependency no predecessor produces is absent."""
        _check(page.id not in {seen.id for seen in self._pages}, f"flow {self.id!r}: repeated page id {page.id!r}")
        gap = {path for path in page.requires if not has(self._shadow, path)}
        _check(not gap, f"flow {self.id!r}: page {page.id!r} needs {sorted(gap)} nothing before it produces")
        _check(
            page.condition is None or page.condition(self._shadow),
            f"flow {self.id!r}: page {page.id!r} rejects its place",
        )
        for path in page.produces:
            seed(self._shadow, path, _PRESENCE)
        self._pages.append(page)
        return self

    def build(self) -> Graph:
        """Freeze the accumulated pages into the walk-safe `Graph` — its own checks are the last net."""
        return Graph(self.id, tuple(self._pages))


def _check(holds: bool, why: str) -> None:  # noqa: FBT001 — the boolean argument IS the predicate
    """Raise `PageStructureError(why)` when `holds` is false."""
    if not holds:
        raise PageStructureError(why)
