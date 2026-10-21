"""tests/unit/e_tui/layout/shape: the figures — plates of the right size, symmetric rings, honest fill."""

import pytest

from e_tui.layout.shape import EllipseShape, PolygonShape
from e_tui.layout.spec import Border, Point

WIDTH, HEIGHT = 30, 12


@pytest.fixture
def ellipse() -> EllipseShape:
    """A plain ellipse painter."""
    return EllipseShape()


@pytest.fixture
def circle() -> EllipseShape:
    """A cell-aspect-corrected circle painter."""
    return EllipseShape(circle=True)


@pytest.fixture
def hexagon() -> PolygonShape:
    """A regular six-sided painter."""
    return PolygonShape(sides=6)


def _rows(
    painter: EllipseShape | PolygonShape, border: Border = Border.FINE, width: int = WIDTH, height: int = HEIGHT
) -> list[str]:
    return painter.paint(width, height, border)


##### PLATE LAW #####


@pytest.mark.parametrize("border", list(Border))
def test_shape_rows_match_the_requested_geometry(ellipse: EllipseShape, border: Border) -> None:
    rows = _rows(ellipse, border)
    assert len(rows) == HEIGHT
    assert all(len(row) == WIDTH for row in rows)


@pytest.mark.parametrize("size", [(0, 0), (1, 1), (2, 1)], ids=["empty", "dot", "sliver"])
def test_shape_paints_degenerate_sizes_without_complaining(ellipse: EllipseShape, size: tuple[int, int]) -> None:
    rows = _rows(ellipse, width=size[0], height=size[1])
    assert len(rows) == size[1]


##### ELLIPSE #####


def test_shape_ellipse_ring_is_hollow_and_centered(ellipse: EllipseShape) -> None:
    rows = _rows(ellipse)
    assert rows[HEIGHT // 2].count("·") == 2  # mid-row: one mark per side
    assert all(row == row[::-1] for row in rows)  # vertical axis of symmetry


def test_shape_ellipse_fill_shades_the_interior(ellipse: EllipseShape) -> None:
    rows = _rows(ellipse, Border.FILL)
    mid = rows[HEIGHT // 2]
    assert "▒" in mid  # interior shaded
    assert "█" in mid  # ring solid


def test_shape_circle_stays_round_not_wide(circle: EllipseShape, ellipse: EllipseShape) -> None:
    square = (WIDTH, WIDTH)
    ellipse_rows = sum(any(ch != " " for ch in row) for row in ellipse.paint(*square, Border.FINE))
    circle_rows = sum(any(ch != " " for ch in row) for row in circle.paint(*square, Border.FINE))
    assert circle_rows < ellipse_rows  # the circle is capped vertically by the 2:1 aspect


##### POLYGON #####


def test_shape_regular_polygon_inks_both_edge_tilts(hexagon: PolygonShape) -> None:
    rows = _rows(hexagon, Border.THICK)
    assert any("━" in row for row in rows)  # flat edges
    assert any("┃" in row for row in rows)  # steep edges


def test_shape_hexagon_is_mirror_symmetric(hexagon: PolygonShape) -> None:
    rows = _rows(hexagon)
    assert all([c != " " for c in row] == [c != " " for c in row[::-1]] for row in rows)  # the ink mask mirrors


def test_shape_irregular_polygon_keeps_the_shape_given() -> None:
    arrow = PolygonShape(points=(Point(0, 0), Point(1, 0.5), Point(0, 1)))
    rows = arrow.paint(20, 7, Border.FINE)
    assert all(row[0] == "│" for row in rows)  # the flat back is a full vertical
    tips = [max(i for i, ch in enumerate(row) if ch != " ") for row in rows]
    assert tips[0] < tips[3] > tips[-1] == tips[0]  # the nose reaches the right only at mid-height


def test_shape_irregular_polygon_uses_given_vertices() -> None:
    triangle = PolygonShape(points=(Point(0, 1), Point(1, 1), Point(0.5, 0)))
    rows = _rows(triangle)
    assert rows[0].strip() != ""  # apex inked
    assert rows[-1].count("─") > HEIGHT  # flat base spans the width


def test_shape_border_none_paints_blank(ellipse: EllipseShape) -> None:
    assert all(set(row) <= {" "} for row in _rows(ellipse, Border.NONE))
