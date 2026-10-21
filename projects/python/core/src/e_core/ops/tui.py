"""ops/tui: HeaderTui — the agnostic retro masthead for any Textual app.

Usage, in any app:

    from ops.tui import HeaderTui

    yield HeaderTui()                        # E-TEMPLATES / EAGER SERIES (square pixels, flush right, ~1/4 height)
    yield HeaderTui("mi app", "beta")        # MI APP / beta  (main always uppercase)
    yield HeaderTui("X", "", color="#ff8800", max_height=12)

Scales to the available width and height in integer steps, never overflows the terminal,
and falls back to a framed compact line when not even the minimum scale fits."""

from functools import lru_cache

from rich.style import Style
from rich.text import Text
from textual.reactive import reactive
from textual.widget import Widget

##### DEFAULTS #####
COLOR: str = "#0277bd"  # dark sky blue: letters and frame
MAX_SCALE: int = 40
MIN_WIDTH: int = 5
SUB_RATIO: int = 4  # the tagline is a quarter of the title height: a tagline, not a second logo

##### FONTS #####
UPPER_SPEC: str = """
A .#./#.#/###/#.#/#.#
B ##./#.#/##./#.#/##.
C .##/#../#../#../.##
D ##./#.#/#.#/#.#/##.
E ###/#../###/#../###
F ###/#../##./#../#..
G .##/#../#.#/#.#/.##
H #.#/#.#/###/#.#/#.#
I ###/.#./.#./.#./###
J ..#/..#/..#/#.#/.#.
K #.#/#.#/##./#.#/#.#
L #../#../#../#../###
M #...#/##.##/#.#.#/#...#/#...#
N #..#/##.#/#.##/#..#/#..#
O ###/#.#/#.#/#.#/###
P ###/#.#/###/#../#..
Q ###/#.#/#.#/###/..#
R ##./#.#/##./#.#/#.#
S ###/#../###/..#/###
T ###/.#./.#./.#./.#.
U #.#/#.#/#.#/#.#/###
V #.#/#.#/#.#/#.#/.#.
W #...#/#...#/#.#.#/##.##/#...#
X #.#/#.#/.#./#.#/#.#
Y #.#/#.#/.#./.#./.#.
Z ###/..#/.#./#../###
0 ###/#.#/#.#/#.#/###
1 .#./##./.#./.#./###
2 ###/..#/###/#../###
3 ###/..#/###/..#/###
4 #.#/#.#/###/..#/..#
5 ###/#../###/..#/###
6 ###/#../###/#.#/###
7 ###/..#/..#/.#./.#.
8 ###/#.#/###/#.#/###
9 ###/#.#/###/..#/###
- .../.../###/.../...
. .../.../.../.../.#.
! .#./.#./.#./.../.#.
: .../.#./.../.#./...
+ .../.#./###/.#./...
"""
UPPER: dict[str, tuple[str, ...]] = {
    key: tuple(rows.split("/")) for item in UPPER_SPEC.split("\n") if item for key, rows in [item.split(" ", 1)]
}
UPPER[" "] = ("..",) * 5
UPPER["/"] = ("..#", "..#", ".#.", "#..", "#..")

BLANK: tuple[str, ...] = ("..",) * 5
### the tagline font below a half-block quarter: 3 pixels tall, drawn in sextants (2x3 pixels per cell) so one
### text row holds a whole glyph — square pixels where half-blocks would need 2.5 rows.
SMALL_SPEC: str = """
A .#./###/#.#
B #../###/###
C ###/#../###
D ##./#.#/##.
E ###/##./###
F ###/##./#..
G ##./#.#/###
H #.#/###/#.#
I ###/.#./###
J ..#/..#/##.
K #.#/##./#.#
L #../#../###
M ###/###/#.#
N ##./#.#/#.#
O ###/#.#/###
P ###/###/#..
Q ###/###/..#
R ##./##./#.#
S .##/.#./##.
T ###/.#./.#.
U #.#/#.#/###
V #.#/#.#/.#.
W #.#/###/###
X #.#/.#./#.#
Y #.#/.#./.#.
Z ##./.#./.##
0 ###/#.#/###
1 ##./.#./###
2 ##./.#./.##
3 ###/.##/###
4 #.#/###/..#
5 .##/.#./##.
6 #../###/###
7 ###/..#/..#
8 ###/###/###
9 ###/###/..#
- .../###/...
. .../.../.#.
: .#./.../.#.
+ .#./###/.#.
/ ..#/.#./#..
"""
SMALL: dict[str, tuple[str, ...]] = {
    key: tuple(rows.split("/")) for item in SMALL_SPEC.split("\n") if item for key, rows in [item.split(" ", 1)]
}
SMALL_BLANK: tuple[str, ...] = ("..",) * 3
SMALL[" "] = SMALL_BLANK
### a sextant's six pixels as bits (top-left = 1 … bottom-right = 32): the block skips the four patterns that
### already exist elsewhere — empty, full, left half, right half.
SEXTANT_REUSED: dict[int, str] = {0: " ", 21: "▌", 42: "▐", 63: "█"}

SEXTANT: dict[int, str] = SEXTANT_REUSED | {
    bits: chr(0x1FB00 + offset) for offset, bits in enumerate(bits for bits in range(64) if bits not in SEXTANT_REUSED)
}
HALF: dict[tuple[bool, bool], str] = {
    (False, False): " ",
    (True, False): "▀",
    (False, True): "▄",
    (True, True): "█",
}


##### TYPES #####
class HeaderTui(Widget):
    """The agnostic retro masthead: a scalable block logo over a frame, on black.

    Args:
        main: the headline text, always rendered uppercase.
        sub: the tagline beneath, flush right in the title's square pixels (default "eager series"; empty hides it).
        color: the stroke color of letters and frame.
        max_height: growth cap only - a float (0-1) is a fraction of the terminal height,
            an int is rows. The smallest scale is always kept if it fits the width.
    """

    DEFAULT_CSS = """
    HeaderTui {
        width: 100%;
        height: auto;
        background: black;
    }
    """

    main = reactive("E-TEMPLATES", layout=True)
    sub = reactive("eager series", layout=True)

    def __init__(
        self,
        main: str = "E-TEMPLATES",
        sub: str = "eager series",
        *,
        color: str = COLOR,
        max_height: int | float = 0.6,
        name: str | None = None,
        id: str | None = None,  # noqa: A002 — textual's widget contract
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self.logo_color = color
        self.max_height = max_height
        self.main = main
        self.sub = sub

    ############################################################

    ##### PRIVATE METHODS #####

    @staticmethod
    def _common_cells(glyphs: list[tuple[str, ...]]) -> int:
        """Width in pixels of a glyph row: one column of separation between glyphs."""
        return sum(len(glyph[0]) for glyph in glyphs) + max(len(glyphs) - 1, 0)

    @staticmethod
    def _common_glyphs(
        text: str, font: dict[str, tuple[str, ...]], blank: tuple[str, ...] = BLANK
    ) -> list[tuple[str, ...]]:
        """Rows per character; unknown characters fall back to the font's blank."""
        return [font.get(ch, blank) for ch in text]

    @staticmethod
    def _common_layout(tc: int, *, tagged: bool) -> tuple[int, int, int, int, int, int]:
        """(half-block tagline cell, sextant tagline cell, border, h-padding, v-padding, gap) at title scale `tc`.

        A title scale divisible by SUB_RATIO holds the tagline as an exact quarter in half-blocks; any other scale
        draws it in sextants, `s` rows tall for the nearest quarter of the title's 2.5·tc rows. 0 means unused."""
        exact = tagged and tc % SUB_RATIO == 0
        ec = tc // SUB_RATIO if exact else 0
        sc = max(1, round(5 * tc / (2 * SUB_RATIO))) if tagged and not exact else 0
        return ec, sc, max(1, ec), tc, max(1, tc // 2), max(1, tc // 2)

    @staticmethod
    def _common_width(tcells: int, sub: str, tc: int) -> int:
        """Columns of the framed logo at title scale `tc`, without building it."""
        ec, sc, bt, padh, _, _ = HeaderTui._common_layout(tc, tagged=bool(sub))
        half = HeaderTui._common_cells(HeaderTui._common_glyphs(sub.upper(), UPPER)) * ec
        fine = -(-HeaderTui._common_cells(HeaderTui._common_glyphs(sub.upper(), SMALL, SMALL_BLANK)) * sc // 2)
        return max(tcells * tc, half, fine) + 2 * (padh + bt)

    @staticmethod
    def _common_bitmap(glyphs: list[tuple[str, ...]], cell: int) -> list[list[bool]]:
        """Pixel grid at scale `cell`: every glyph row followed by a blank separator, stretched on both axes."""
        height = len(glyphs[0]) if glyphs else len(BLANK)
        lines = [
            [on for glyph in glyphs for ch in (*glyph[row], ".") for on in [ch == "#"] * cell] for row in range(height)
        ]
        return [line[: HeaderTui._common_cells(glyphs) * cell] for line in lines for _ in range(cell)]

    @staticmethod
    def _common_frame(rows: list[list[bool]], inner: int, bt: int, padh: int) -> list[list[bool]]:
        """Each row flush right in `inner`, padded by `padh` and walled by `bt` border pixels on both sides."""
        return [[True] * bt + [False] * (padh + inner - len(row)) + row + [False] * padh + [True] * bt for row in rows]

    @staticmethod
    def _common_even(rows: list[list[bool]], at: int, spacer: list[bool]) -> list[list[bool]]:
        """An even pixel height (two per text row): one spacer row inserted at `at` when odd."""
        return rows if len(rows) % 2 == 0 else [*rows[:at], spacer, *rows[at:]]

    @staticmethod
    def _common_halves(rows: list[list[bool]]) -> tuple[str, ...]:
        """Pixel rows paired into half-block text rows."""
        return tuple(
            "".join(HALF[pair] for pair in zip(top, bottom, strict=True))
            for top, bottom in zip(*[iter(rows)] * 2, strict=True)
        )

    @staticmethod
    def _common_sextants(rows: list[list[bool]]) -> tuple[str, ...]:
        """Pixel rows packed three high and two wide into sextant cells (U+1FB00 block, plus the four it reuses)."""
        width = max((len(row) for row in rows), default=0)
        width += width % 2
        grid = [row + [False] * (width - len(row)) for row in rows]
        grid += [[False] * width] * (-len(grid) % 3)
        return tuple(
            "".join(
                SEXTANT[sum(grid[y + dy][x + dx] << (2 * dy + dx) for dy in range(3) for dx in range(2))]
                for x in range(0, width, 2)
            )
            for y in range(0, len(grid), 3)
        )

    @staticmethod
    def _common_compact(main: str, sub: str, width: int) -> tuple[str, ...]:
        """The minimum version (framed plain text) for when not even scale 1 fits."""
        match width < MIN_WIDTH:
            case True:
                return (main[: max(width, 0)],)
            case _:
                return (
                    "█" * width,
                    *(f"█ {text[: width - 4].center(width - 4)} █" for text in (main, sub) if text),
                    "█" * width,
                )

    @staticmethod
    @lru_cache(maxsize=64)
    def _common_art(main: str, sub: str, tc: int) -> tuple[str, ...]:
        """The framed logo as text rows: the title, then the tagline flush right beneath it in square pixels at about
        a quarter of the title height — half-blocks when the quarter is exact, one sextant row per cell otherwise."""
        ec, sc, bt, padh, padv, gap = HeaderTui._common_layout(tc, tagged=bool(sub))
        title = HeaderTui._common_bitmap(HeaderTui._common_glyphs(main, UPPER), tc)
        half = HeaderTui._common_bitmap(HeaderTui._common_glyphs(sub.upper(), UPPER), ec) if ec else []
        fine = (
            HeaderTui._common_sextants(
                HeaderTui._common_bitmap(HeaderTui._common_glyphs(sub.upper(), SMALL, SMALL_BLANK), sc)
            )
            if sc
            else ()
        )
        inner = max(len(title[0]), len(half[0]) if half else 0, len(fine[0]) if fine else 0)
        width = inner + 2 * (padh + bt)
        wall, spacer = [True] * width, [True] * bt + [False] * (width - 2 * bt) + [True] * bt
        pad = [[] for _ in range(padv)]
        upper = [*[wall] * bt, *HeaderTui._common_frame([*pad, *title, *[[]] * gap, *half], inner, bt, padh)]
        lower = [*HeaderTui._common_frame(pad, inner, bt, padh), *[wall] * bt]
        tagline = tuple(f"{'█' * bt}{' ' * (padh + inner - len(row))}{row}{' ' * padh}{'█' * bt}" for row in fine)
        return (
            *HeaderTui._common_halves(HeaderTui._common_even(upper, len(upper), spacer)),
            *tagline,
            *HeaderTui._common_halves(HeaderTui._common_even(lower, 0, spacer)),
        )

    @staticmethod
    def _common_pick(main: str, sub: str, avail_w: int, max_rows: int) -> int | None:
        """The largest title scale that fits width and height; None when none fits the width.

        The smallest width-fitting scale is always kept, even if it overgrows the height."""
        tcells = HeaderTui._common_cells(HeaderTui._common_glyphs(main, UPPER))
        fits = [tc for tc in range(MAX_SCALE, 0, -1) if HeaderTui._common_width(tcells, sub, tc) <= avail_w]
        return next(
            (tc for tc in fits if len(HeaderTui._common_art(main, sub, tc)) <= max_rows), fits[-1] if fits else None
        )

    def _common_max_rows(self) -> int:
        """Row cap from `max_height`: an int is rows, a float a fraction of the terminal height."""
        match self.max_height:
            case int() as rows:
                return rows
            case ratio:
                return max(1, int(self.app.size.height * ratio))

    def _common_lines(self, width: int) -> tuple[str, ...]:
        """Every half-block row of the masthead at this width: the one source for render and height."""
        match HeaderTui._common_pick(self.main, self.sub, width, self._common_max_rows()):
            case None:
                return HeaderTui._common_compact(self.main, self.sub, width)
            case scale:
                return HeaderTui._common_art(self.main, self.sub, scale)

    ############################################################

    ##### PUBLIC #####

    def validate_main(self, value: str) -> str:
        return value.upper()

    def get_content_height(self, container, viewport, width: int) -> int:  # noqa: ARG002 — textual's sizing contract
        return len(self._common_lines(width))

    def render(self) -> Text:
        width = self.size.width
        lines = self._common_lines(width)
        left = " " * max(0, (width - len(lines[0])) // 2)
        return Text(
            "\n".join(left + line for line in lines),
            style=Style(color=self.logo_color),
            no_wrap=True,
            overflow="crop",
        )
