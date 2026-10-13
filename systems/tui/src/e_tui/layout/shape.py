"""e_tui.layout.shape: the basic figures rasterized to cells — the outline painters behind the frames.

A terminal is a grid: circles and polygons are approximations, and this module owns that honesty. Each
painter turns a box size and border treatment into rows of glyphs, consumed by
`e_tui.layout.frame.EdgeFrame` — no Textual, no async, pure geometry as one marks-then-plate pipeline:
comprehensions produce a `{cell: glyph}` marking, `_plate` prints it to text rows.

Ellipses are parametric-sampled around the box center; a *circle* keeps the 2:1 cell aspect. Polygons are
regular (n sides, inscribed) or irregular (explicit normalized points), edges sampled between vertices.
"""

from math import cos, floor, pi, sin
from typing import Final, Protocol

from e_tui.layout.spec import Border, Point

##### PAINTER #####


class Painter(Protocol):
    """Anything that can rasterize itself to glyph rows at a given size and treatment."""

    def paint(self, width: int, height: int, border: Border) -> list[str]: ...


##### GLYPHS #####
_GLYPHS: Final[dict[Border, str]] = {  # the ring glyph per treatment
    Border.FINE: "·",
    Border.THICK: "●",
    Border.FILL: "█",
    Border.NONE: " ",
}
_INNER: Final[str] = "▒"  # the shade a FILL figure paints inside its ring
_EDGE_GLYPHS: Final[dict[Border, tuple[str, str]]] = {  # per edge: (flat, steep), slope picks between them
    Border.FINE: ("─", "│"),
    Border.THICK: ("━", "┃"),
    Border.FILL: ("▬", "▮"),
    Border.NONE: (" ", " "),
}
_STEPS: Final[int] = 8  # samples per cell of travel: dense enough that thin lines stay connected


##### PLATE #####


def _cell(value: float) -> int:
    """Uniform round-half-up: Python's banker's rounding would make .5-centered figures asymmetric."""
    return floor(value + 0.5)


def _plate(marks: dict[tuple[int, int], str], width: int, height: int) -> list[str]:
    """Print a {cell: glyph} marking onto text rows, blank elsewhere."""
    return ["".join(marks.get((x, y), " ") for x in range(width)) for y in range(height)]


def _lerp(a: int, b: int, t: float) -> float:
    """Point at fraction `t` between `a` and `b`."""
    return a + (b - a) * t


def _segment(x0: int, y0: int, x1: int, y1: int) -> set[tuple[int, int]]:
    """Cell centers on the segment, sampled parametrically — never per-pixel stepping."""
    travel = max(abs(x1 - x0), abs(y1 - y0)) * _STEPS
    return (
        {(x0, y0)}
        if not travel
        else {(_cell(_lerp(x0, x1, t)), _cell(_lerp(y0, y1, t))) for t in (i / travel for i in range(travel + 1))}
    )


def _tilt(dx: int, dy: int, pair: tuple[str, str]) -> str:
    """The edge glyph matching a segment's tilt: the flat or the steep one."""
    flat, steep = pair
    return flat if abs(dx) >= abs(dy) else steep


##### PAINTERS #####


class EllipseShape:
    """Ellipse outlines sampled around the box center; `circle` keeps the figure round in 2:1 cells."""

    def __init__(self, *, circle: bool = False) -> None:
        self._circle = circle

    def paint(self, width: int, height: int, border: Border) -> list[str]:
        """Rows of glyphs for the figure at this size and treatment (`FILL` shades the interior)."""
        if min(width, height) <= 0:
            return [" " * max(width, 0) for _ in range(max(height, 0))]
        cx, cy, a, b = self._geometry(width, height)
        draws = _samples(width, height)
        ring = {
            (_cell(cx + a * cos(t)), _cell(cy + b * sin(t))) for t in (2 * pi * i / draws for i in range(draws + 1))
        }
        marks = dict.fromkeys(ring, _GLYPHS[border]) | self._interior(width, height, (cx, cy, a, b), border)
        return _plate(marks, width, height)

    def _geometry(self, width: int, height: int) -> tuple[float, float, float, float]:
        """Center and radii of the figure: a circle is capped by the shorter reach at 2:1 cells."""
        cx, cy = (width - 1) / 2, (height - 1) / 2
        a, b = (min(2 * cy, cx), min(cy, cx / 2)) if self._circle else (cx, cy)
        return cx, cy, a, b

    def _interior(
        self, width: int, height: int, geo: tuple[float, float, float, float], border: Border
    ) -> dict[tuple[int, int], str]:
        """The cells inside the figure, marked — empty unless the treatment is `fill`."""
        cx, cy, a, b = geo
        return {
            (x, y): _INNER
            for x in range(width)
            for y in range(height)
            if border is Border.FILL and a > 0 and b > 0 and ((x - cx) / a) ** 2 + ((y - cy) / b) ** 2 <= 1
        }


class PolygonShape:
    """Regular (n sides, inscribed) or irregular (explicit points) polygon outlines."""

    def __init__(self, sides: int = 0, points: tuple[Point, ...] = ()) -> None:
        self._sides = sides
        self._points = points

    def paint(self, width: int, height: int, border: Border) -> list[str]:
        """Rows of glyphs: every edge marked with the glyph matching its tilt.

        A regular polygon is mirror-symmetric about the vertical axis through its point-up apex, and the
        plate keeps that promise — marks are unioned with their x-mirror. An irregular one is painted
        exactly as given, no symmetry invented."""
        pairs = self._vertices(width, height)
        flat, steep = _EDGE_GLYPHS[border]
        marks = {
            cell: _tilt(x1 - x0, y1 - y0, (flat, steep))
            for (x0, y0), (x1, y1) in zip(pairs, pairs[1:] + pairs[:1], strict=False)
            for cell in {(x0, y0), (x1, y1)} | _segment(x0, y0, x1, y1)
        }
        return _plate(self._mirrored(marks, width), width, height)

    def _mirrored(self, marks: dict[tuple[int, int], str], width: int) -> dict[tuple[int, int], str]:
        """The marking plus its reflection on the vertical axis — regular figures only."""
        if self._points:
            return marks
        return marks | {(width - 1 - x, y): glyph for (x, y), glyph in marks.items()}

    def _vertices(self, width: int, height: int) -> list[tuple[int, int]]:
        """Vertices scaled to cells: explicit points win, else a regular n-gon point-up in the box."""
        if self._points:
            return [(_cell(p.x * (width - 1)), _cell(p.y * (height - 1))) for p in self._points]
        cx, cy = (width - 1) / 2, (height - 1) / 2
        angles = (2 * pi * i / self._sides - pi / 2 for i in range(self._sides))
        return [(_cell(cx + cx * cos(t)), _cell(cy + cy * sin(t))) for t in angles]


def _samples(width: int, height: int) -> int:
    """The ellipse is sampled once per 1/_STEPS cell of its longest axis."""
    return max(width, height) * _STEPS
