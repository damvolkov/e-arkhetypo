"""tests/integration/e_tui/layout/render: the compiler dispatches shapes to frames and fills slots."""

import pytest
from textual.widgets import ListView, Static

from e_tui.app import LayoutApp
from e_tui.layout.frame import BoxFrame, EdgeFrame
from e_tui.layout.spec import Axis, Box, Kind, Mast, Measure, Shape
from e_tui.models.error import SpecError
from ops.tui import HeaderTui

##### FIXTURES #####


def _spec() -> Box:
    return Box(
        id="stage",
        kind=Kind.STATIC,
        axis=Axis.ROW,
        size=Measure(frac=1.0),
        children=(
            Box(id="field", kind=Kind.DYNAMIC, size=Measure(frac=0.5)),
            Box(id="orb", kind=Kind.DYNAMIC, shape=Shape.ELLIPSE, size=Measure(frac=0.5)),
        ),
    )


##### DISPATCH #####


async def test_render_sends_rect_to_boxframe_and_ellipse_to_edgeframe() -> None:
    app = LayoutApp(_spec())
    async with app.run_test(size=(60, 20)) as pilot:
        await pilot.pause()
        assert isinstance(app.query_one("#field"), BoxFrame)
        assert isinstance(app.query_one("#orb"), EdgeFrame)


##### FILL #####


async def test_render_injects_widget_seed_into_named_slot() -> None:
    app = LayoutApp(_spec(), fill={"field": Static("seeded")})
    async with app.run_test(size=(60, 20)) as pilot:
        await pilot.pause()
        field = app.query_one("#field", BoxFrame)
        assert any(isinstance(c, Static) for c in field.children)


async def test_render_injects_many_widgets_from_a_sequence() -> None:
    app = LayoutApp(_spec(), fill={"field": [Static("a"), Static("b")]})
    async with app.run_test(size=(60, 20)) as pilot:
        await pilot.pause()
        field = app.query_one("#field", BoxFrame)
        assert sum(isinstance(c, Static) for c in field.children) >= 2


async def test_edgeframe_ellipse_renders_a_full_width_ring_line() -> None:
    app = LayoutApp(_spec())
    async with app.run_test(size=(60, 20)) as pilot:
        await pilot.pause()
        orb = app.query_one("#orb", EdgeFrame)
        line = orb.render_line(orb.size.height // 2)
        assert line.cell_count == orb.size.width
        assert any(seg.text.strip() for seg in line)  # the mid-line carries the figure's ink


##### MASTHEAD DISPATCH #####


async def test_render_mounts_the_house_pixel_engine_for_a_masthead_box() -> None:
    spec = Box(
        id="top",
        kind=Kind.STATIC,
        size=Measure(frac=1.0),
        mast=Mast(main="PIXEL", sub="tag"),
    )
    app = LayoutApp(spec)
    async with app.run_test(size=(60, 20)) as pilot:
        await pilot.pause()
        frame = app.query_one("#top", BoxFrame)
        assert any(isinstance(child, HeaderTui) for child in frame.children)


##### APP SURFACE #####


async def test_app_reports_its_fillable_slots() -> None:
    app = LayoutApp(_spec())
    async with app.run_test(size=(60, 20)):
        assert set(app.slots()) == {"field", "orb"}


async def test_app_fill_mounts_late_into_an_existing_frame() -> None:
    app = LayoutApp(_spec())
    async with app.run_test(size=(60, 20)) as pilot:
        await pilot.pause()
        app.fill("field", ListView())
        await pilot.pause()
        assert any(isinstance(c, ListView) for c in app.query_one("#field", BoxFrame).children)


async def test_app_fill_rejects_a_slot_the_spec_never_reserved() -> None:
    app = LayoutApp(_spec())
    async with app.run_test(size=(60, 20)):
        with pytest.raises(SpecError, match="no such dynamic slot"):
            app.fill("ghost", Static("x"))


async def test_app_fill_replaces_previous_slot_content() -> None:
    app = LayoutApp(_spec(), fill={"field": Static("first")})
    async with app.run_test(size=(60, 20)) as pilot:
        await pilot.pause()
        app.fill("field", Static("second"))
        await pilot.pause()
        kids = [c for c in app.query_one("#field", BoxFrame).children if isinstance(c, Static)]
        assert len(kids) == 1
