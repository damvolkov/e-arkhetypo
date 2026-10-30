"""tests/unit/e_infra/ops/tui: HeaderTui behavior — render and content height at every width, never internals."""

from typing import TYPE_CHECKING

import pytest

from e_infra.ops.tui import HeaderTui

if TYPE_CHECKING:
    from collections.abc import Callable

    from textual.app import App

##### SIZES: huge, wide, medium, narrow, tiny, absurd #####
SIZES: list[tuple[int, int]] = [(200, 50), (90, 22), (40, 16), (20, 12), (8, 6), (3, 4)]
FRAMED: list[tuple[int, int]] = [(200, 50), (60, 20), (10, 8)]
PIXELS: dict[str, tuple[bool, bool]] = {" ": (False, False), "▀": (True, False), "▄": (False, True), "█": (True, True)}


def _bands(lines: list[str]) -> list[int]:
    """Heights in pixels of the inked row bands inside the frame: full-ink rows and full-ink columns are frame."""
    grid = [[PIXELS.get(ch, (True, True)) for ch in line] for line in lines]
    rows = [[cell[half] for cell in line] for line in grid for half in (0, 1)]
    walls = {x for x in range(len(rows[0])) if all(row[x] for row in rows)}
    inked = [not all(row) and any(on for x, on in enumerate(row) if x not in walls) for row in rows]
    runs = "".join("#" if on else "." for on in inked).split(".")
    return [len(run) for run in runs if run]


@pytest.mark.parametrize(("width", "height"), SIZES, ids=["huge", "wide", "medium", "narrow", "tiny", "absurd"])
async def test_tui_render_never_overflows(host_app: Callable[[HeaderTui], App[None]], width: int, height: int) -> None:
    """No line crosses the terminal width, no block crosses its height, and the height promise holds."""
    app = host_app(HeaderTui())
    async with app.run_test(size=(width, height)):
        header = app.screen.query_one(HeaderTui)
        lines = str(header.render()).splitlines()
        assert lines
        assert all(len(line) <= width for line in lines)
        assert len(lines) <= height
        assert header.get_content_height(0, 0, width) == len(lines)


@pytest.mark.parametrize(("width", "height"), FRAMED, ids=["huge", "medium", "compact"])
async def test_tui_frames_the_logo(host_app: Callable[[HeaderTui], App[None]], width: int, height: int) -> None:
    """Art or compact fallback: the outer rows are pure frame, and the logo paints inside them."""
    app = host_app(HeaderTui())
    async with app.run_test(size=(width, height)):
        header = app.screen.query_one(HeaderTui)
        lines = [line.lstrip() for line in str(header.render()).splitlines()]
        assert set(lines[0]) <= {"█", "▀"}
        assert lines[0][0] == lines[0][-1] == "█"
        assert set(lines[-1]) <= {"█", "▄"}
        assert lines[-1][0] == lines[-1][-1] == "█"
        assert any(any(cell in line for cell in "▀▄█") for line in lines[1:-1])


async def test_tui_sub_is_a_tagline_not_a_second_logo(host_app: Callable[[HeaderTui], App[None]]) -> None:
    """At the same scale, the sub grows the block by less than the title already is."""
    bare = host_app(HeaderTui("AB", "", max_height=1))
    tagged = host_app(HeaderTui("AB", "cd", max_height=1))
    async with bare.run_test(size=(120, 40)):
        title_rows = bare.screen.query_one(HeaderTui).get_content_height(0, 0, 120)
    async with tagged.run_test(size=(120, 40)):
        full_rows = tagged.screen.query_one(HeaderTui).get_content_height(0, 0, 120)
    assert 0 < full_rows - title_rows < title_rows


@pytest.mark.parametrize(("width", "height"), [(200, 50), (400, 120)], ids=["wide", "huge"])
async def test_tui_title_is_four_times_the_tagline(
    host_app: Callable[[HeaderTui], App[None]], width: int, height: int
) -> None:
    """Wherever the tagline is drawn as a bitmap, the title band is exactly four times taller."""
    app = host_app(HeaderTui())
    async with app.run_test(size=(width, height)):
        lines = [line.strip() for line in str(app.screen.query_one(HeaderTui).render()).splitlines()]
        title, tagline = _bands(lines)
        assert title == 4 * tagline


@pytest.mark.parametrize(("width", "height"), [(60, 20), (120, 30)], ids=["scale-1", "scale-2"])
async def test_tui_tagline_is_one_sextant_row_where_half_blocks_cannot_quarter(
    host_app: Callable[[HeaderTui], App[None]], width: int, height: int
) -> None:
    """Below scale 4 the tagline packs into sextants: a single text row, flush right against the frame."""
    app = host_app(HeaderTui())
    async with app.run_test(size=(width, height)):
        lines = [line.strip() for line in str(app.screen.query_one(HeaderTui).render()).splitlines()]
        tagline = [line for line in lines if any(0x1FB00 <= ord(ch) <= 0x1FB3B for ch in line)]
        assert len(tagline) == 1
        assert len(lines) - 2 > 2 * len(tagline), "the title must stand well above the tagline"
        assert tagline[0].rstrip("█").endswith(" "), "flush right, inside the padding"


async def test_tui_falls_back_to_compact_frame(host_app: Callable[[HeaderTui], App[None]]) -> None:
    """Where not even scale 1 fits, a framed plain-text block answers within the width."""
    app = host_app(HeaderTui())
    async with app.run_test(size=(8, 6)):
        header = app.screen.query_one(HeaderTui)
        lines = str(header.render()).splitlines()
        assert len(lines) == 4
        assert all(len(line) == 8 for line in lines)
        assert "E" in lines[1]
        assert "e" in lines[2]


async def test_tui_reacts_to_new_text(host_app: Callable[[HeaderTui], App[None]]) -> None:
    """The main reactive always renders uppercase and repaints through the same contract."""
    app = host_app(HeaderTui("AB", "cd"))
    async with app.run_test(size=(90, 22)) as pilot:
        header = app.screen.query_one(HeaderTui)
        header.main = "zz"
        header.sub = ""
        await pilot.pause()
        assert header.main == "ZZ"
        assert str(header.render()).strip()
