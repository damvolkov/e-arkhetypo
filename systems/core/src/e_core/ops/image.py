"""ops/image: deterministic square-font logos — solid background, rect glyphs, `prefix` + `-` + name.

Every wordmark is the same claim: a 1024 square canvas, one background rect, one group of rect glyphs
in the house square font. The font is the table `GLYPHS`: letters A-Z and the hyphen, each built from
axis-aligned rects on a 255x436 box (stroke 45, pitch 292), anchored by the reference `E` reproduced
byte-for-byte from `assets/eager.svg`. A word wider than the canvas scales as a whole: the geometry is
uniform, never re-flowed, so the same name always emits the same bytes. Colors vary freely; the
defaults capture the reference: background `#060c15`, letter `#166b7e`. A name that already
carries the prefix passes through, `filename` spells the file the wordmark belongs to, and `save` writes it to disk."""

import re
from enum import StrEnum
from fractions import Fraction
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from msgspec import Struct

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping
    from pathlib import Path

CANVAS: Final[int] = 1024
TOP: Final[int] = 257
HEIGHT: Final[int] = 436
WIDTH: Final[int] = 255
PITCH: Final[int] = 292
FILL: Final[int] = 950
PAD: Final[int] = 4
BACKGROUND: Final[str] = "#060c15"
FOREGROUND: Final[str] = "#166b7e"
PREFIX: Final[str] = "e"

##### TYPES #####


class LogoError(ValueError):
    """A name, prefix or color the generator refuses to render."""


class Glyph(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"
    F = "F"
    G = "G"
    H = "H"
    I = "I"  # noqa: E741 — the alphabet names its glyphs by letter
    J = "J"
    K = "K"
    L = "L"
    M = "M"
    N = "N"
    O = "O"  # noqa: E741 — the alphabet names its glyphs by letter
    P = "P"
    Q = "Q"
    R = "R"
    S = "S"
    T = "T"
    U = "U"
    V = "V"
    W = "W"
    X = "X"
    Y = "Y"
    Z = "Z"
    HYPHEN = "-"


class Rect(Struct):
    """One rect glyph stroke: position inside the letter box, width, height."""

    x: int
    y: int
    w: int
    h: int


##### FONT #####
GLYPHS: Final[Mapping[Glyph, tuple[Rect, ...]]] = MappingProxyType(
    {
        Glyph.E: (Rect(0, 0, 49, 436), Rect(0, 0, 255, 45), Rect(0, 172, 219, 45), Rect(0, 391, 255, 45)),
        Glyph.HYPHEN: (Rect(0, 172, 219, 45),),
        Glyph.A: (Rect(0, 0, 45, 436), Rect(210, 0, 45, 436), Rect(0, 0, 255, 45), Rect(0, 194, 255, 45)),
        Glyph.B: (
            Rect(0, 0, 45, 436),
            Rect(0, 0, 255, 45),
            Rect(0, 194, 255, 45),
            Rect(0, 391, 255, 45),
            Rect(210, 0, 45, 239),
            Rect(210, 194, 45, 242),
        ),
        Glyph.C: (Rect(0, 0, 255, 45), Rect(0, 391, 255, 45), Rect(0, 0, 45, 436)),
        Glyph.D: (Rect(0, 0, 45, 436), Rect(210, 0, 45, 436), Rect(0, 0, 255, 45), Rect(0, 391, 255, 45)),
        Glyph.F: (Rect(0, 0, 45, 436), Rect(0, 0, 255, 45), Rect(0, 194, 219, 45)),
        Glyph.G: (
            Rect(0, 0, 255, 45),
            Rect(0, 391, 255, 45),
            Rect(0, 0, 45, 436),
            Rect(210, 194, 45, 242),
            Rect(135, 194, 120, 45),
        ),
        Glyph.H: (Rect(0, 0, 45, 436), Rect(210, 0, 45, 436), Rect(0, 194, 255, 45)),
        Glyph.I: (Rect(0, 0, 255, 45), Rect(0, 391, 255, 45), Rect(105, 0, 45, 436)),
        Glyph.J: (Rect(210, 0, 45, 436), Rect(0, 391, 255, 45), Rect(105, 0, 150, 45)),
        Glyph.K: (Rect(0, 0, 45, 436), Rect(0, 194, 255, 45), Rect(210, 0, 45, 194), Rect(210, 239, 45, 197)),
        Glyph.L: (Rect(0, 0, 45, 436), Rect(0, 391, 255, 45)),
        Glyph.M: (Rect(0, 0, 45, 436), Rect(210, 0, 45, 436), Rect(105, 0, 45, 239), Rect(0, 0, 255, 45)),
        Glyph.N: (
            Rect(0, 0, 45, 436),
            Rect(210, 0, 45, 436),
            Rect(44, 91, 58, 96),
            Rect(98, 187, 58, 96),
            Rect(148, 283, 68, 96),
        ),
        Glyph.O: (Rect(0, 0, 255, 45), Rect(0, 391, 255, 45), Rect(0, 0, 45, 436), Rect(210, 0, 45, 436)),
        Glyph.P: (Rect(0, 0, 45, 436), Rect(0, 0, 255, 45), Rect(0, 194, 255, 45), Rect(210, 0, 45, 239)),
        Glyph.Q: (
            Rect(0, 0, 255, 45),
            Rect(0, 391, 255, 45),
            Rect(0, 0, 45, 436),
            Rect(210, 0, 45, 436),
            Rect(135, 291, 98, 100),
        ),
        Glyph.R: (
            Rect(0, 0, 45, 436),
            Rect(0, 0, 255, 45),
            Rect(0, 194, 255, 45),
            Rect(210, 0, 45, 239),
            Rect(180, 239, 75, 197),
        ),
        Glyph.S: (
            Rect(0, 0, 255, 45),
            Rect(0, 194, 255, 45),
            Rect(0, 391, 255, 45),
            Rect(0, 0, 45, 239),
            Rect(210, 194, 45, 242),
        ),
        Glyph.T: (Rect(0, 0, 255, 45), Rect(105, 0, 45, 436)),
        Glyph.U: (Rect(0, 0, 45, 436), Rect(210, 0, 45, 436), Rect(0, 391, 255, 45)),
        Glyph.V: (Rect(0, 0, 45, 291), Rect(210, 0, 45, 291), Rect(105, 291, 45, 145)),
        Glyph.W: (Rect(0, 0, 45, 436), Rect(210, 0, 45, 436), Rect(105, 194, 45, 242)),
        Glyph.X: (
            Rect(0, 0, 58, 96),
            Rect(46, 91, 58, 96),
            Rect(98, 187, 58, 96),
            Rect(150, 283, 58, 96),
            Rect(202, 374, 53, 62),
            Rect(197, 0, 58, 96),
            Rect(150, 91, 58, 96),
            Rect(44, 283, 62, 96),
            Rect(0, 374, 53, 62),
        ),
        Glyph.Y: (Rect(0, 0, 45, 239), Rect(210, 0, 45, 239), Rect(105, 194, 45, 242)),
        Glyph.Z: (
            Rect(0, 0, 255, 45),
            Rect(0, 391, 255, 45),
            Rect(150, 91, 62, 96),
            Rect(98, 187, 58, 96),
            Rect(44, 283, 62, 96),
        ),
    }
)

GLYPH_CHARS: Final[frozenset[str]] = frozenset(glyph.value for glyph in Glyph)
_COLOR: Final[re.Pattern[str]] = re.compile(r"#[0-9a-fA-F]{6}")

##### GENERATOR #####


class LogoGenerator(Struct, frozen=True, kw_only=True):
    """Wordmark as svg: background rect plus the name in the square font, prefixed by `prefix-`."""

    background: str = BACKGROUND
    foreground: str = FOREGROUND
    prefix: str = PREFIX

    def __post_init__(self) -> None:
        self._check_color(self.background, "background")
        self._check_color(self.foreground, "foreground")
        match bad := set(self.prefix.upper()) - GLYPH_CHARS:
            case _ if bad:
                msg = f"prefix letters outside the square font: {sorted(bad)!r}"
                raise LogoError(msg)
            case _:
                return

    ##### PRIVATE #####

    @staticmethod
    def _check_color(value: str, field: str) -> None:
        match value:
            case str() if _COLOR.fullmatch(value):
                return
            case _:
                msg = f"{field} must be a 6-digit hex color, got {value!r}"
                raise LogoError(msg)

    def _generate_text(self, name: str) -> str:
        """The wordmark spelled out: prefix, hyphen, name — a name already prefixed is left as it is."""
        match name:
            case "":
                msg = "an empty name renders nothing"
                raise LogoError(msg)
            case _:
                prefix = (
                    "" if not self.prefix or name.lower().startswith(f"{self.prefix.lower()}-") else f"{self.prefix}-"
                )
                text = prefix + name
                match bad := set(text.upper()) - GLYPH_CHARS:
                    case _ if bad:
                        msg = f"letters outside the square font: {sorted(bad)!r}"
                        raise LogoError(msg)
                    case _:
                        return text

    @staticmethod
    def _generate_layout(text: str) -> tuple[Fraction, int, int]:
        """Scale, origin x and origin y: natural at 1, whole-word uniform shrink past the canvas."""
        width = len(text) * PITCH - (PITCH - WIDTH)
        scale = Fraction(FILL, width) if width > FILL else Fraction(1)
        origin_x = int((CANVAS - width * scale) / 2)
        origin_y = TOP if scale == 1 else int((CANVAS - HEIGHT * scale) / 2)
        return scale, origin_x, origin_y

    @staticmethod
    def _generate_rects(text: str, scale: Fraction, origin_x: int, origin_y: int) -> Iterator[Rect]:
        """Every stroke of the word, canvas-relative, in reading order."""
        for index, char in enumerate(text):
            base_x = origin_x + int(index * PITCH * scale)
            yield from (
                Rect(
                    base_x + int(rect.x * scale),
                    origin_y + int(rect.y * scale),
                    int(rect.w * scale),
                    int(rect.h * scale),
                )
                for rect in GLYPHS[Glyph(char.upper())]
            )

    def _generate_lines(self, text: str) -> Iterator[str]:
        """The svg as its lines: header, background, one group of glyph rects."""
        scale, origin_x, origin_y = self._generate_layout(text)
        yield f'<svg width="{CANVAS}" height="{CANVAS}" viewBox="0 0 {CANVAS} {CANVAS}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="{text}">'
        yield f'  <rect width="{CANVAS}" height="{CANVAS}" fill="{self.background}"/>'
        yield f'  <g fill="{self.foreground}">'
        yield from (
            f'    <rect x="{rect.x}" y="{rect.y}" width="{rect.w}"{" " * (PAD - len(f"{rect.w}"))}height="{rect.h}"/>'
            for rect in self._generate_rects(text, scale, origin_x, origin_y)
        )
        yield "  </g>"
        yield "</svg>"

    ############################################################

    ##### PUBLIC #####

    def generate(self, name: str) -> str:
        """The svg wordmark of `name`: same name, same colors, same bytes, always."""
        text = self._generate_text(name)
        return "\n".join(self._generate_lines(text)) + "\n"

    def save(self, name: str, path: Path) -> Path:
        """The wordmark written to `path`; parents created, path returned."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.generate(name), encoding="utf-8")
        return path

    def filename(self, name: str) -> str:
        """The file the wordmark belongs to: the text it spells, svg-suffixed."""
        return f"{self._generate_text(name)}.svg"
