"""e_tui.flow.page: one node of the walk — what it shows, what it depends on, and where it leads.

A `Page` is interior, code-owned — hence a plain frozen dataclass, not a wire struct. It carries a
callable `route`, the conditional edge that decides the next page from the user's commit (the langgraph
idiom), and the declaration that fixes its *place* in the flow: `requires` the state paths it reads and
some earlier page must produce, `produces` the paths it writes when accepted, `condition` a placement gate
checked the moment the page is added, `on_commit` a hook deriving domain data into the shared state.
With no `route` a page falls to `next`, and with no `next` to declaration order; a page with neither is
terminal. `route` reads a live value at walk time; `condition` reads declared presence at add time — the
boundary between them is what keeps the walk free of structural errors (see `e_tui.flow.pages`)."""

from collections.abc import Callable, Mapping, MutableMapping
from dataclasses import dataclass, field

from e_tui.models.object import Commit, Spec

Route = Callable[[Commit, Mapping[str, object]], "str | None"]
Condition = Callable[[Mapping[str, object]], bool]
Hook = Callable[[Commit, MutableMapping[str, object]], None]


@dataclass(frozen=True, slots=True)
class Page:
    """A station on the flow: show `spec`, take a commit, then `route` it — or fall through to `next`."""

    id: str
    title: str
    spec: Spec
    requires: frozenset[str] = frozenset()
    produces: frozenset[str] = frozenset()
    condition: Condition | None = None
    next: str | None = None
    route: Route | None = None
    on_commit: Hook | None = None
    meta: Mapping[str, object] = field(default_factory=dict)
