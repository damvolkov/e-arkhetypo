"""tests/unit: LogoGenerator — deterministic square-font svg: reference letter byte-for-byte, prefix, colors, refusal."""

import re
from typing import TYPE_CHECKING

import pytest

from e_core.ops.image import GLYPHS, Glyph, LogoError, LogoGenerator

if TYPE_CHECKING:
    from pathlib import Path

EAGER_E = """<svg width="1024" height="1024" viewBox="0 0 1024 1024" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="e">
  <rect width="1024" height="1024" fill="#060c15"/>
  <g fill="#166b7e">
    <rect x="384" y="257" width="49"  height="436"/>
    <rect x="384" y="257" width="255" height="45"/>
    <rect x="384" y="429" width="219" height="45"/>
    <rect x="384" y="648" width="255" height="45"/>
  </g>
</svg>
"""


def test_the_reference_letter_is_reproduced_byte_for_byte() -> None:
    assert LogoGenerator(prefix="").generate("e") == EAGER_E


def test_the_default_word_carries_the_house_prefix() -> None:
    assert 'aria-label="e-taxis"' in LogoGenerator().generate("taxis")


def test_a_prefixed_word_is_not_prefixed_twice() -> None:
    assert LogoGenerator().generate("e-taxis") == LogoGenerator().generate("taxis")


def test_the_filename_is_the_wordmark_it_spells() -> None:
    assert LogoGenerator().filename("taxis") == "e-taxis.svg"
    assert LogoGenerator(prefix="").filename("eager") == "eager.svg"


def test_the_same_word_and_colors_emit_the_same_bytes_across_instances() -> None:
    bare, explicit = LogoGenerator(), LogoGenerator(background="#060c15", foreground="#166b7e")
    assert bare.generate("taxis") == explicit.generate("taxis")


def test_colors_vary_without_varying_the_geometry() -> None:
    inverted = LogoGenerator(prefix="", background="#ffffff", foreground="#000000").generate("e")
    assert inverted.replace("#ffffff", "#060c15").replace("#000000", "#166b7e") == EAGER_E


def test_every_letter_of_the_font_has_a_glyph() -> None:
    assert set(GLYPHS) == set(Glyph)


def test_a_word_wider_than_the_canvas_shrinks_as_a_whole() -> None:
    rects = [
        (int(x), int(w))
        for x, w in re.findall(r'<rect x="(\d+)" y="\d+" width="(\d+)"', LogoGenerator().generate("templates"))
    ]
    assert max(x + w for x, w in rects) <= 1024
    assert rects[0][1] < 49


def test_letters_outside_the_square_font_are_refused() -> None:
    with pytest.raises(LogoError, match="letters outside"):
        LogoGenerator().generate("tax!s")


def test_an_empty_name_is_refused() -> None:
    with pytest.raises(LogoError, match="empty name"):
        LogoGenerator().generate("")


@pytest.mark.parametrize("field", ["background", "foreground"])
def test_a_color_that_is_not_six_hex_digits_is_refused_up_front(field: str) -> None:
    with pytest.raises(LogoError, match=field):
        LogoGenerator(**{field: "navy"})


def test_save_writes_the_wordmark_creating_parents(tmp_path: Path) -> None:
    target = tmp_path / "assets" / "e-taxis.svg"
    assert LogoGenerator().save("taxis", target).read_text() == LogoGenerator().generate("taxis")
