"""tests/unit/e_tui/layout/test_spec: the geometry language — validation law, tree views, file loading."""

from typing import TYPE_CHECKING, Any

import pytest

from e_tui.layout.spec import Axis, Border, Box, Kind, Line, Mast, Measure, Point, Shape
from e_tui.models.error import SpecError

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

##### VOCABULARY #####


def test_spec_defaults_describe_a_reserved_rect(make_leaf: Callable[..., Box]) -> None:
    leaf = make_leaf()
    assert leaf.shape is Shape.RECT
    assert leaf.border is Border.FINE
    assert leaf.axis is Axis.OVERLAY
    assert leaf.size.frac == 1.0
    assert leaf.children == ()
    assert leaf.lines == ()


def test_spec_measure_accepts_relative_and_clamped_forms() -> None:
    tight = Measure(frac=0.4, weight=2.0, min_cells=3, max_cells=40)
    assert (tight.frac, tight.weight, tight.min_cells, tight.max_cells) == (0.4, 2.0, 3, 40)


@pytest.mark.parametrize(
    "bad",
    [{"size": Measure(frac=1.4)}, {"cross": Measure(frac=-0.1)}, {"offset": Point(x=2.0)}, {"padding": -1}],
    ids=["frac-hi", "frac-neg", "offset", "padding"],
)
def test_spec_rejects_illegal_geometry(make_leaf: Callable[..., Box], bad: dict[str, Any]) -> None:
    with pytest.raises(SpecError):
        make_leaf(**bad)


@pytest.mark.parametrize("bad", [{"min_cells": 10, "max_cells": 4}, {"min_cells": -2}], ids=["undercut", "negative"])
def test_spec_rejects_contradictory_clamps(make_leaf: Callable[..., Box], bad: dict[str, int]) -> None:
    with pytest.raises(SpecError):
        make_leaf(size=Measure(**bad))


##### KIND LAW #####


def test_spec_dynamic_box_needs_no_lines(make_leaf: Callable[..., Box]) -> None:
    assert make_leaf().lines == ()


def test_spec_lines_only_belong_to_static_boxes() -> None:
    static = Box(id="band", kind=Kind.STATIC, lines=(Line(text="hi"),))
    assert static.lines[0].emphasis == 0
    with pytest.raises(SpecError, match="only a static box"):
        Box(id="x", kind=Kind.DYNAMIC, lines=(Line(text="nope"),))


@pytest.mark.parametrize("emphasis", [3, -1, 99])
def test_spec_rejects_unknown_emphasis(emphasis: int) -> None:
    with pytest.raises(SpecError, match="emphasis"):
        Box(kind=Kind.STATIC, lines=(Line(text="x", emphasis=emphasis),))


##### MASTHEAD #####


def test_spec_masthead_belongs_to_static_boxes_only(make_leaf: Callable[..., Box]) -> None:
    with pytest.raises(SpecError, match="masthead"):
        make_leaf(mast=Mast(main="PIXEL"))


def test_spec_masthead_and_lines_are_exclusive(make_leaf: Callable[..., Box]) -> None:
    with pytest.raises(SpecError, match="not lines"):
        make_leaf(kind=Kind.STATIC, lines=(Line(text="x"),), mast=Mast(main="PIXEL"))


def test_spec_masthead_defaults_are_minimal() -> None:
    mast = Mast(main="E-TUI")
    assert mast.sub == ""
    assert 0.0 < mast.max_height <= 1.0


##### SHAPES #####


@pytest.mark.parametrize(
    "polygon",
    [{"sides": 2}, {"sides": 9}, {"sides": 4, "points": (Point(0, 0), Point(1, 1), Point(1, 0))}],
    ids=["too-few", "too-many", "both"],
)
def test_spec_polygon_must_be_regular_or_irregular_never_both(
    make_leaf: Callable[..., Box], polygon: dict[str, Any]
) -> None:
    with pytest.raises(SpecError, match="polygon"):
        make_leaf(shape=Shape.POLYGON, **polygon)


def test_spec_geometry_fields_only_on_their_shape(make_leaf: Callable[..., Box]) -> None:
    with pytest.raises(SpecError, match="belong to a polygon"):
        make_leaf(sides=4)


@pytest.mark.parametrize("figure", [Shape.ELLIPSE, Shape.CIRCLE])
def test_spec_curved_figures_need_no_extra_fields(make_leaf: Callable[..., Box], figure: Shape) -> None:
    assert make_leaf(shape=figure).shape is figure


def test_spec_irregular_polygon_of_normalized_points_is_well_formed(make_leaf: Callable[..., Box]) -> None:
    field = make_leaf(shape=Shape.POLYGON, points=(Point(0, 0), Point(1, 0), Point(1, 1), Point(0, 1)))
    assert len(field.points) == 4
    with pytest.raises(SpecError, match="polygon points"):
        make_leaf(shape=Shape.POLYGON, points=(Point(-0.5, 0), Point(1, 0), Point(1, 1)))


##### TREE LAW #####


def test_spec_depth_three_is_the_law() -> None:
    three = Box(
        kind=Kind.DYNAMIC, axis=Axis.COLUMN, children=(Box(kind=Kind.DYNAMIC, children=(Box(kind=Kind.DYNAMIC),)),)
    )
    assert len(list(three.walk())) == 3
    with pytest.raises(SpecError, match="deeper"):
        Box(
            kind=Kind.DYNAMIC,
            axis=Axis.COLUMN,
            children=(Box(kind=Kind.DYNAMIC, children=(Box(kind=Kind.DYNAMIC, children=(Box(kind=Kind.DYNAMIC),)),)),),
        )


def test_spec_walk_is_parents_before_children() -> None:
    tree = Box(id="root", kind=Kind.DYNAMIC, axis=Axis.COLUMN, children=(Box(id="kid", kind=Kind.DYNAMIC),))
    assert [node.id for node in tree.walk()] == ["root", "kid"]


def test_spec_duplicate_ids_are_rejected() -> None:
    with pytest.raises(SpecError, match="duplicate slot id"):
        Box(
            kind=Kind.DYNAMIC,
            axis=Axis.COLUMN,
            children=(Box(id="x", kind=Kind.DYNAMIC), Box(id="x", kind=Kind.DYNAMIC)),
        )


def test_spec_slots_collects_only_dynamic_named_boxes() -> None:
    tree = Box(
        id="stage",
        kind=Kind.STATIC,
        axis=Axis.COLUMN,
        children=(Box(id="fill", kind=Kind.DYNAMIC), Box(id="band", kind=Kind.STATIC, lines=(Line(text="t"),))),
    )
    assert set(tree.slots()) == {"fill"}


##### FILE LOAD #####


def test_spec_load_reads_yaml_tree(template_resources: Path) -> None:
    spec = Box.load(template_resources / "config/layout.yml")
    assert spec.id == "frame"
    assert spec.border is Border.THICK
    assert spec.axis is Axis.ROW
    left, orb = spec.children
    assert left.size.weight == 1.0
    assert orb.shape is Shape.CIRCLE
    assert orb.lines[0] == Line(text="ROUND", emphasis=2)
    assert set(spec.slots()) == {"left"}


@pytest.mark.parametrize("suffix", ["toml", "json"])
def test_spec_load_round_trips_every_serial_format(
    write_spec: Callable[[Path, str, Box], None], suffix: str, tmp_path: Path
) -> None:
    original = Box(
        id="root", kind=Kind.DYNAMIC, axis=Axis.ROW, children=(Box(id="kid", kind=Kind.DYNAMIC, border=Border.THICK),)
    )
    source = tmp_path / f"arch.{suffix}"
    write_spec(source, suffix, original)
    assert Box.load(source) == original


def test_spec_load_fails_as_one_error_type(tmp_path: Path) -> None:
    broken = tmp_path / "broken.yml"
    broken.write_text("kind: dynamic\naxis: teleport\n", encoding="utf-8")
    with pytest.raises(SpecError):
        Box.load(broken)
