"""tests/integration/e_tui/layout: the compiled frames — geometry resolved against the live terminal."""

from typing import TYPE_CHECKING

from textual.widgets import Static

from e_tui.app import LayoutApp
from e_tui.layout.frame import BoxFrame, EdgeFrame
from e_tui.layout.spec import Axis, Border, Box, Kind, Measure, Point, Shape

if TYPE_CHECKING:
    from textual.app import App

##### FIXTURES #####


def _stage(*children: Box) -> Box:
    """A bare dynamic stage wrapping the boxes under test."""
    return Box(id="stage", kind=Kind.DYNAMIC, axis=Axis.COLUMN, size=Measure(frac=1.0), children=children)


def _host(spec: Box) -> App[None]:
    return LayoutApp(spec)


##### FLOW GEOMETRY #####


async def test_frame_column_stacks_children_top_to_bottom() -> None:
    spec = _stage(
        Box(id="top", kind=Kind.DYNAMIC, size=Measure(frac=0.25)),
        Box(id="bottom", kind=Kind.DYNAMIC, size=Measure(frac=0.75)),
    )
    app = _host(spec)
    async with app.run_test(size=(60, 40)) as pilot:
        await pilot.pause()
        top, bottom = app.query_one("#top"), app.query_one("#bottom")
        inner = app.query_one("#stage").content_size.height
        assert top.region.height == inner // 4
        assert bottom.region.y == top.region.y + top.region.height


async def test_frame_row_splits_width_left_to_right() -> None:
    spec = _stage(
        Box(
            id="a",
            kind=Kind.DYNAMIC,
            axis=Axis.ROW,
            size=Measure(frac=1.0),
            children=(
                Box(id="l", kind=Kind.DYNAMIC, size=Measure(frac=0.3)),
                Box(id="r", kind=Kind.DYNAMIC, size=Measure(frac=0.7)),
            ),
        )
    )
    app = _host(spec)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        left, right = app.query_one("#l"), app.query_one("#r")
        assert left.region.x < right.region.x
        assert left.region.width + right.region.width <= app.query_one("#a").content_size.width


async def test_frame_weight_shares_the_leftover_space() -> None:
    spec = _stage(
        Box(id="fixed", kind=Kind.DYNAMIC, size=Measure(frac=0.2)),
        Box(id="flex", kind=Kind.DYNAMIC, size=Measure(weight=1.0)),
    )
    app = _host(spec)
    async with app.run_test(size=(40, 50)) as pilot:
        await pilot.pause()
        stage_inner = app.query_one("#stage").content_size.height
        assert app.query_one("#flex").region.height == stage_inner - app.query_one("#fixed").region.height


async def test_frame_column_rescales_on_resize() -> None:
    spec = _stage(Box(id="half", kind=Kind.DYNAMIC, size=Measure(frac=0.5)))
    app = _host(spec)
    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause()
        first = app.query_one("#half").region.height
    async with _host(spec).run_test(size=(80, 80)) as pilot:
        await pilot.pause()
        assert pilot.app.query_one("#half").region.height > first


##### OVERLAY ANCHORING #####


async def test_frame_overlay_anchors_children_by_offset() -> None:
    spec = _stage(
        Box(
            id="ov",
            kind=Kind.DYNAMIC,
            axis=Axis.OVERLAY,
            size=Measure(frac=1.0),
            children=(
                Box(id="tr", kind=Kind.DYNAMIC, size=Measure(frac=0.3), cross=Measure(frac=0.3), offset=Point(x=1.0)),
                Box(id="bl", kind=Kind.DYNAMIC, size=Measure(frac=0.3), cross=Measure(frac=0.3), offset=Point(y=1.0)),
            ),
        )
    )
    app = _host(spec)
    async with app.run_test(size=(100, 50)) as pilot:
        await pilot.pause()
        tr, bl = app.query_one("#tr"), app.query_one("#bl")
        assert tr.region.x > bl.region.x  # top-right sits right of bottom-left
        assert bl.region.y > tr.region.y


##### CLAMPS #####


async def test_frame_min_cells_floor_bites_before_the_fraction() -> None:
    spec = _stage(Box(id="floor", kind=Kind.DYNAMIC, size=Measure(frac=0.1, min_cells=12)))
    app = _host(spec)
    async with app.run_test(size=(40, 30)) as pilot:
        await pilot.pause()
        assert app.query_one("#floor").region.height >= 12


async def test_frame_max_cells_ceils_the_content_of_a_greedy_fraction() -> None:
    spec = _stage(Box(id="ceiling", kind=Kind.DYNAMIC, size=Measure(frac=1.0, max_cells=10)))
    app = _host(spec)
    async with app.run_test(size=(60, 40)) as pilot:
        await pilot.pause()
        assert app.query_one("#ceiling").content_size.height <= 10  # the clamp bites inside the chrome


##### TREATMENT + SHAPE WIRING #####


async def test_frame_fill_border_paints_the_box_corporate_and_hides_border() -> None:
    spec = _stage(Box(id="band", kind=Kind.STATIC, border=Border.FILL, size=Measure(frac=0.5)))
    app = _host(spec)
    async with app.run_test(size=(40, 20)) as pilot:
        await pilot.pause()
        band = app.query_one("#band", BoxFrame)
        assert band.styles.border_top[0] == ""  # hidden resolves to no border token
        assert band.styles.background == band.palette.corporate


async def test_render_routes_curved_boxes_to_edge_frames() -> None:
    spec = _stage(
        Box(id="disc", kind=Kind.DYNAMIC, shape=Shape.CIRCLE, size=Measure(frac=0.5), cross=Measure(frac=0.5)),
    )
    app = _host(spec)
    async with app.run_test(size=(40, 20)) as pilot:
        await pilot.pause()
        assert isinstance(app.query_one("#disc"), EdgeFrame)


async def test_render_leaves_an_unfilled_slot_empty_but_present() -> None:
    spec = _stage(Box(id="gap", kind=Kind.DYNAMIC, size=Measure(frac=0.5)))
    app = _host(spec)
    async with app.run_test(size=(40, 20)) as pilot:
        await pilot.pause()
        slot = app.query_one("#gap", BoxFrame)
        assert slot.content_region.width > 0


async def test_render_mixes_slot_content_and_child_frames() -> None:
    spec = _stage(
        Box(
            id="mixed",
            kind=Kind.DYNAMIC,
            axis=Axis.COLUMN,
            size=Measure(frac=1.0),
            children=(Box(id="kid", kind=Kind.DYNAMIC, size=Measure(frac=0.5)),),
        )
    )
    app = LayoutApp(spec, fill={"mixed": Static("seed")})
    async with app.run_test(size=(40, 20)) as pilot:
        await pilot.pause()
        mixed = app.query_one("#mixed", BoxFrame)
        assert any(isinstance(child, Static) for child in mixed.children)
        assert app.query_one("#kid") is not None
