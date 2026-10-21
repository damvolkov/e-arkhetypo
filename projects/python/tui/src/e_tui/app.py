"""e_tui.app: LayoutApp — the host application that mounts a compiled architecture and fills its slots.

The app is deliberately thin: it owns a spec tree and a slot mapping, compiles them through
`e_tui.layout.render.LayoutRender`, and exposes `fill` so a running process can drop widgets into any
`DYNAMIC` slot after mount. The frames, colors and geometry are the template's business, not the app's —
that is the whole point of the split. Subclass and set `SPEC` for a concrete architecture, or pass one in.

    class Wizard(LayoutApp):
        SPEC = StandardTemplate.SPEC

    app = Wizard()
    app.fill("content", ListView(...))

`WizardApp` is the same host driven by a `e_tui.flow` graph: it walks pages, mounting the current page's
interactive object into `content`, the walked trail into `steps`, and back/accept/reset into `keys`. The
viewer is dumb — every move answers a typed `Move` and it simply matches it.
"""

from collections.abc import Callable, Iterable, Mapping
from typing import TYPE_CHECKING, ClassVar, cast

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widget import Widget
from textual.widgets import Static

from e_tui.flow.walk import Finished, Move, OnPage, Walker
from e_tui.interact.registry import build
from e_tui.layout.render import SLOT_CLASS, LayoutRender
from e_tui.models.error import SpecError
from e_tui.templates.standard import StandardTemplate

if TYPE_CHECKING:
    from e_tui.flow.graph import Graph
    from e_tui.interact.ports import ObjectPort
    from e_tui.layout.spec import Box

##### RESULT #####

ResultView = Callable[[Mapping[str, object]], Iterable[Widget]]
"""What the host wants to see once the walk finishes — the shared state turned into widgets."""


class LayoutApp(App[None]):
    """An app whose whole chrome is one compiled spec tree; slots receive widgets at runtime."""

    SPEC: ClassVar[Box] = StandardTemplate.SPEC

    def __init__(self, spec: Box | None = None, fill: Mapping[str, Widget | Iterable[Widget]] | None = None) -> None:
        """Override the class spec and/or seed slot contents (a second `fill` layer, by id)."""
        super().__init__()
        self.spec = spec if spec is not None else type(self).SPEC
        self._fill: dict[str, Widget | Iterable[Widget]] = dict(fill or {})

    ############################################################

    def compose(self) -> ComposeResult:
        """Mount the single compiled root frame; seeds already injected ride inside it."""
        yield from LayoutRender(self.spec, self._fill).frames()

    def fill(self, slot: str, *widgets: Widget) -> None:
        """Replace a dynamic slot's content idempotently, leaving structural sub-frames (e.g. `steps`) intact."""
        self._check_slot(slot)
        self._fill[slot] = self._collapse(widgets)
        fresh = self._slots(self._fill[slot])
        for widget in fresh:
            widget.add_class(SLOT_CLASS)
        for node in self.query(f"#{slot}"):
            [child.remove() for child in list(node.children) if child.has_class(SLOT_CLASS)]
            node.mount(*fresh)

    def slots(self) -> tuple[str, ...]:
        """The dynamic slot ids the current spec declares — the app's fillable surface."""
        return tuple(self.spec.slots())

    ##### PRIVATE #####

    def _check_slot(self, slot: str) -> None:
        """Fail loudly when the app fills a name the spec never reserved."""
        if slot not in self.spec.slots():
            why = f"no such dynamic slot: {slot!r}"
            raise SpecError(why)

    @staticmethod
    def _collapse(widgets: tuple[Widget, ...]) -> Widget | Iterable[Widget]:
        """A single widget stays a widget; many become the tuple the renderer accepts."""
        return widgets[0] if len(widgets) == 1 else widgets

    @staticmethod
    def _slots(content: Widget | Iterable[Widget]) -> tuple[Widget, ...]:
        """Normalize slot content back to a tuple, for post-mount re-filling."""
        return (content,) if isinstance(content, Widget) else tuple(content)


class WizardApp(LayoutApp):
    """A `LayoutApp` driven by a flow graph: the page under the cursor fills `content`, its trail `steps`, its controls `keys`."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("enter", "page_accept", "accept", priority=True),  # advance regardless of what holds focus
        Binding("backspace", "page_back", "back"),
        Binding("escape", "page_back", "back"),
        Binding("ctrl+r", "page_reset", "reset", priority=True),
        Binding("ctrl+q", "quit", "quit", priority=True),
    ]

    def __init__(self, graph: Graph, spec: Box | None = None, result: ResultView | None = None) -> None:
        """Host one flow over the standard architecture (or an explicit `spec`).

        `result` is an optional seam: a `State` → widgets callable the viewer mounts once the walk
        finishes, so the host — not the template — decides what the accumulated data model looks like.
        """
        super().__init__(spec)
        self._walk = Walker(graph)
        self._result = result
        self._object: ObjectPort | None = None

    ############################################################

    ##### PUBLIC #####

    KEY_HINT: ClassVar[str] = "arrows move · space select · enter accept · backspace back · ctrl+r reset · ctrl+q quit"

    def on_mount(self) -> None:
        """Paint the keys hint once, then render the entry page into the dynamic slots."""
        self.fill("keys", Static(self.KEY_HINT, markup=False))  # a one-row strip fits text, not 3-row buttons
        self._render()

    def action_page_accept(self) -> None:
        """Advance the walk by accepting the mounted object — the `enter` binding."""
        self._accept()

    def action_page_back(self) -> None:
        """Reverse one page — the `backspace`/`escape` binding."""
        self._apply(self._walk.back())

    def action_page_reset(self) -> None:
        """Wipe the walk to the entry — the `ctrl+r` binding."""
        self._apply(self._walk.reset())

    ##### PRIVATE #####

    def _render(self) -> None:
        """Show the page under the cursor: its object in content, the walked trail as the timeline."""
        page = self._walk.here()
        self._object = build(page.spec, self._walk.state.values_for(page.id))
        view = cast("Widget", self._object)  ### every interactive object the registry makes is also a Textual Widget.
        self.fill("content", view)
        self.fill("steps", Static(self._timeline(), markup=False))  # the brackets are literal, not Rich markup
        self.set_focus(view)

    def _accept(self) -> None:
        """Commit the mounted object if it holds an answer; the route or successor decides where it lands."""
        commit = self._object.commit() if self._object is not None else None
        if commit is not None:
            self._apply(self._walk.advance(commit))

    def _apply(self, move: Move) -> None:
        """React to a typed move: a page re-renders, the end shows the result, a refusal or the head does nothing."""
        match move:
            case OnPage():
                self._render()
            case Finished():
                self._end()
            case _:
                return

    def _end(self) -> None:
        """The walk ran past the last page — mount the host's result view, or a bare end marker."""
        self._object = None
        self.fill("content", *self._result(self._walk.state.data) if self._result else [Static("done")])

    def _timeline(self) -> str:
        """The trail, read-only: the pages walked behind, then the cursor bracketed."""
        graph, trail, at = self._walk.state.graph, self._walk.state.trail, self._walk.state.at
        return " · ".join(f"[{graph.page(pid).title}]" if pid == at else graph.page(pid).title for pid in (*trail, at))
