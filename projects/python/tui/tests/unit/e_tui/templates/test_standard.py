"""tests/unit/e_tui/templates/standard: the derivation holds the drawing's contract."""

from e_tui.layout.spec import Axis, Border, Kind
from e_tui.templates.standard import StandardTemplate

##### THE SPEC #####
SPEC = StandardTemplate.SPEC
HEADER, CONTENT, KEYS = SPEC.children
(STEPS,) = CONTENT.children


def test_standard_nests_exactly_three_levels() -> None:
    assert len(list(SPEC.walk())) == 5  # stage, header, content, steps, keys
    assert not HEADER.children
    assert not STEPS.children


def test_standard_declares_the_three_slots_under_the_same_names() -> None:
    assert set(SPEC.slots()) == {"content", "steps", "keys"}


def test_standard_stacks_header_field_and_keys_in_the_stage() -> None:
    assert SPEC.axis is Axis.COLUMN
    assert HEADER.kind is Kind.STATIC
    assert CONTENT.size.weight == 1.0  # the field owns the leftover screen
    assert KEYS.kind is Kind.DYNAMIC
    assert KEYS.border is Border.NONE  # the strip carries no frame


def test_standard_header_is_a_pixel_masthead_not_plain_type() -> None:
    assert HEADER.mast is not None
    assert HEADER.mast.main
    assert not HEADER.lines  # the masthead replaces the lines, it never mixes with them


def test_standard_steps_band_is_one_row_wide_of_the_field() -> None:
    assert CONTENT.axis is Axis.OVERLAY
    assert STEPS in CONTENT.walk()
    assert STEPS.cross.min_cells == 1
    assert STEPS.cross.max_cells == 1  # a single row
    assert STEPS.size.frac < 1.0  # inset from the right edge


def test_standard_keys_strip_is_a_single_row() -> None:
    assert KEYS.size.min_cells == 1
    assert KEYS.size.max_cells == 1
