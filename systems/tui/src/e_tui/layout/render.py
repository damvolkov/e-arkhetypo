"""e_tui.layout.render: the compiler — a validated spec tree becomes a mounted tree of frames.

`LayoutRender` walks the `Box` tree bottom-up and builds the widget tree: each box becomes a `BoxFrame`
(or `EdgeFrame` for the non-rectangular figures, with its painter), static lines become `Static` labels
in corporate type, and every `DYNAMIC` box mounts whatever the app injected into its slot — leaving the
space reserved when the app injected nothing. Geometry is not decided here: each frame re-resolves its
children on resize, so the whole tree is responsive by construction.

    LayoutRender(Box.load(path), fill={"content": ListView(...)}).frames()   # one root widget
"""

from collections.abc import Callable, Iterable, Iterator, Mapping
from types import MappingProxyType
from typing import Final

from rich.text import Text
from textual.widget import Widget
from textual.widgets import Static

from core.settings import settings as st
from e_tui.layout.frame import BoxFrame, Colors, EdgeFrame, ThemeSource
from e_tui.layout.shape import EllipseShape, Painter, PolygonShape
from e_tui.layout.spec import Box, Line, Mast, Shape
from ops.tui import HeaderTui

##### DISPATCH #####
SLOT_CLASS: Final[str] = "slot-content"  # marks widgets an app mounted into a dynamic slot (vs. structural frames)
_EMPHASIS: Final[Mapping[int, str]] = MappingProxyType({0: "none", 1: "italic", 2: "bold"})


def _rect(box: Box, colors: Colors, children: list[Widget]) -> BoxFrame:
    """A rectangular box wears its native border."""
    return BoxFrame(box, colors, *children)


def _arc(box: Box, colors: Colors, children: list[Widget]) -> BoxFrame:
    """Any other figure paints its own ring."""
    return EdgeFrame(box, colors, _PAINTERS[box.shape](box), *children)


_FRAMES: Final[Mapping[Shape, Callable[[Box, Colors, list[Widget]], BoxFrame]]] = MappingProxyType(
    dict.fromkeys(Shape, _arc) | {Shape.RECT: _rect}
)
_PAINTERS: Final[Mapping[Shape, Callable[[Box], Painter]]] = MappingProxyType(
    {
        Shape.ELLIPSE: lambda _: EllipseShape(),
        Shape.CIRCLE: lambda _: EllipseShape(circle=True),
        Shape.POLYGON: lambda box: PolygonShape(box.sides, box.points),
    }
)


class LayoutRender:
    """Compiles one spec tree into one frame tree, filling dynamic slots from the app's mapping."""

    def __init__(
        self,
        root: Box,
        fill: Mapping[str, Widget | Iterable[Widget]] = MappingProxyType({}),
        theme: ThemeSource | None = None,
    ) -> None:
        """Hold the spec, the slot contents and the theme (default: the house settings)."""
        self._root = root
        self._fill = fill
        self._colors = Colors.from_settings(theme if theme is not None else st.theme)

    ############################################################

    ##### PUBLIC #####

    def frames(self) -> Iterator[Widget]:
        """Yield the single root frame, sized to fill its screen."""
        root = self._build(self._root, floating=False)
        root.styles.width, root.styles.height = "100%", "100%"
        yield root

    ##### PRIVATE #####

    def _build(self, box: Box, *, floating: bool = True) -> BoxFrame:
        """Build one box and its subtree: child frames first, then static lines, then slot content."""
        static = [self._mast(box.mast)] if box.mast is not None else [self._label(line) for line in box.lines]
        children: list[Widget] = self._slot(box) + [self._build(child) for child in box.children] + static
        frame = _FRAMES[box.shape](box, self._colors, children)
        frame.styles.position = "absolute" if floating else "relative"
        return frame

    def _mast(self, mast: Mast) -> Widget:
        """The declared pixel masthead, drawn by the house engine in the corporate hue."""
        return HeaderTui(mast.main, mast.sub, color=self._colors.corporate.hex, max_height=mast.max_height)

    def _label(self, line: Line) -> Widget:
        """One static line: plain text in corporate, emphasis mapped to the house styles."""
        label = Static(Text(line.text))
        label.styles.color = self._colors.corporate
        label.styles.text_style = _EMPHASIS[line.emphasis]
        return label

    def _slot(self, box: Box) -> list[Widget]:
        """Whatever the app injected for this box's id — empty when the slot stays reserved."""
        if box.id is None or box.id not in self._fill:
            return []
        provided = self._fill[box.id]
        widgets = [provided] if isinstance(provided, Widget) else list(provided)
        for widget in widgets:
            widget.add_class(SLOT_CLASS)  # tagged so a later `fill` clears only content, never a sub-frame
        return widgets
