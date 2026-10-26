"""e_tui.layout.frame: the frame widgets — a box's chrome (border, background, padding) as Textual containers.

Two classes, one per border reality. `BoxFrame` is a rectangular container wearing the native Textual
border its treatment calls for (`FINE` solid, `THICK` heavy, `FILL` no border and corporate background —
a painted band, `NONE` invisible). `EdgeFrame` is the same container for the curved and angular figures:
an invisible grid box whose ring of glyphs is painted by an `e_tui.layout.shape` painter, its children
sitting in the inscribed rectangle. Both speak exactly three colors, handed in as `Colors` from the
theme: background under everything, corporate for frames and static type, ink for dynamic content."""

from dataclasses import dataclass
from itertools import accumulate, groupby
from typing import Final, Protocol

from rich.segment import Segment
from rich.style import Style
from textual.color import Color
from textual.containers import Container
from textual.css.types import EdgeType
from textual.events import Resize
from textual.strip import Strip
from textual.widget import Widget

from e_tui.layout.shape import Painter
from e_tui.layout.spec import Axis, Border, Box, Measure, Shape

##### BORDERS #####
_NATIVE: Final[dict[Border, EdgeType]] = {
    Border.FINE: "solid",
    Border.THICK: "heavy",
    Border.FILL: "hidden",
    Border.NONE: "hidden",
}
_VERTICAL: Final[dict[Axis, bool]] = {Axis.ROW: False, Axis.COLUMN: True, Axis.OVERLAY: False}
_BLANK: Final[str] = " "


class ThemeSource(Protocol):
    """The theme fields a `Colors` needs — infra's `ThemeSettings` satisfies it without import."""

    theme_background: str
    theme_corporate: str
    theme_ink: str


@dataclass(frozen=True, slots=True)
class Colors:
    """The three-color law, resolved from theme settings: background, corporate, ink."""

    background: Color
    corporate: Color
    ink: Color

    @classmethod
    def from_settings(cls, theme: ThemeSource) -> Colors:
        """Build from any object carrying the three hex fields (duck-typed: no infra import here)."""
        return cls(
            background=Color.parse(theme.theme_background),
            corporate=Color.parse(theme.theme_corporate),
            ink=Color.parse(theme.theme_ink),
        )


class BoxFrame(Container):
    """A box wearing its chrome (border or fill, colors, padding) and owning its children's geometry.

    The frame is a miniature flex engine: relative measures (`Measure.frac`/`weight`) resolve against the
    live content area on every resize, along the parent box's axis — `ROW` splits width, `COLUMN` splits
    height, `OVERLAY` floats each child to its fractional anchor. Cell clamps (`min_cells`/`max_cells`)
    cut in last, so proportions stay honest but never illegible."""

    def __init__(self, box: Box, palette: Colors, *children: Widget) -> None:
        super().__init__(*children, id=box.id)
        self.box = box
        self.palette = palette
        self.styles.background = palette.corporate if box.border is Border.FILL else palette.background
        self.styles.color = palette.ink
        self.styles.padding = (box.padding, box.padding, box.padding, box.padding)
        self.styles.border = (_NATIVE[box.border], palette.corporate)

    ############################################################

    def on_resize(self, event: Resize) -> None:  # noqa: ARG002 — textual's handler contract
        """Re-resolve every child frame against the new content area."""
        self._arrange()

    ##### PRIVATE #####

    def _arrange(self) -> None:
        """Place this box's child frames along its axis; plain content children flow untouched."""
        frames = [child for child in self.children if isinstance(child, BoxFrame)]
        vertical = _VERTICAL[self.box.axis]
        main, cross = (
            (self.content_size.height, self.content_size.width)
            if vertical
            else (self.content_size.width, self.content_size.height)
        )
        sizes = self._main_sizes(frames, main)
        [
            self._place(frame, size, start, cross, vertical=vertical)
            for frame, size, start in zip(frames, sizes, self._anchors(frames, main, sizes), strict=True)
        ]

    def _place(self, frame: BoxFrame, size: int, start: int, cross: int, *, vertical: bool) -> None:
        """One child frame: main size at the running start, cross fraction anchored in the free space."""
        box = frame.box
        cross_size = self._clamped(box.cross, int(cross * box.cross.frac), box)
        anchor = int((cross - cross_size) * (box.offset.x if vertical else box.offset.y))
        frame.styles.height, frame.styles.width = (size, cross_size) if vertical else (cross_size, size)
        frame.styles.offset = (anchor, start) if vertical else (start, anchor)

    def _main_sizes(self, frames: list[BoxFrame], main: int) -> list[int]:
        """Main-axis sizes: unweighted children take their `frac` of the box; weighted ones split the leftover."""
        weights = sum(frame.box.size.weight for frame in frames)
        fixed = sum(
            self._clamped(frame.box.size, int(main * frame.box.size.frac), frame.box)
            for frame in frames
            if frame.box.size.weight == 0
        )
        left = max(0, main - fixed)
        weights = weights or 1.0
        return [
            self._clamped(frame.box.size, int(left * frame.box.size.weight / weights), frame.box)
            if frame.box.size.weight
            else self._clamped(frame.box.size, int(main * frame.box.size.frac), frame.box)
            for frame in frames
        ]

    def _clamped(self, measure: Measure, frame_size: int, box: Box) -> int:
        """One main-axis size: the clamps bite in *content* cells — border, ring and padding ride on top."""
        chrome = self._chrome(box)
        inner = max(0, frame_size - chrome)
        capped = min(inner, measure.max_cells) if measure.max_cells is not None else inner
        return chrome + max(measure.min_cells, capped)

    @staticmethod
    def _chrome(box: Box) -> int:
        """Cells the border (or the painted ring) and the padding consume along one axis."""
        edge = 2 if box.shape is not Shape.RECT or box.border in (Border.FINE, Border.THICK) else 0
        return edge + 2 * box.padding

    def _anchors(self, frames: list[BoxFrame], main: int, sizes: list[int]) -> list[int]:
        """Main-axis starts: cumulative for a flow, fractional anchor for an overlay."""
        return (
            [
                int((main - size) * (frame.box.offset.y if _VERTICAL[self.box.axis] else frame.box.offset.x))
                for frame, size in zip(frames, sizes, strict=True)
            ]
            if self.box.axis is Axis.OVERLAY
            else list(accumulate((0, *sizes)))[:-1]
        )


class EdgeFrame(BoxFrame):
    """A non-rectangular box: its border is a rasterized ring of glyphs, its children sit inside."""

    def __init__(self, box: Box, palette: Colors, painter: Painter, *children: Widget) -> None:
        super().__init__(box, palette, *children)
        self._painter = painter
        self.styles.border = ("hidden", palette.corporate)  # the figure replaces the native border
        ring = box.padding + 1  # keep content clear of the ring
        self.styles.padding = (ring, ring, ring, ring)
        self._plate: list[str] = []

    ############################################################

    def on_resize(self, event: Resize) -> None:
        """Repaint the figure and re-place the children whenever the box changes size."""
        self._plate = self._painter.paint(event.size.width, event.size.height, self.box.border)
        self.refresh()
        self._arrange()

    def render_line(self, y: int) -> Strip:
        """The figure's row at `y`: corporate glyphs over the background, blanks elsewhere."""
        row = (self._plate[y] if y < len(self._plate) else "").ljust(self.size.width)[: self.size.width]
        segments = [Segment("".join(run), self._style(inked=glyph != _BLANK)) for glyph, run in groupby(row)]
        return Strip(segments, self.size.width)

    ##### PRIVATE #####

    def _style(self, *, inked: bool) -> Style:
        """The rich style for one run: corporate figure or plain background."""
        return Style(
            color=self.palette.corporate.rich_color if inked else None,
            bgcolor=self.palette.background.rich_color,
        )
