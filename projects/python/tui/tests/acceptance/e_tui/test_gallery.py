"""tests/acceptance/e_tui/test_gallery: every architecture, every viewport — SVG drift is the verdict.

The visual contract of the whole framework: render each registered architecture at each viewport and
compare against the accepted SVG under ``__snapshots__``. Change a frame, a border, a glyph — the gate
turns red until a human reviews the new picture and accepts it (``--snapshot-update``). The registry
lives in the directory conftest; these names are the ids of the matrix."""

from typing import TYPE_CHECKING

import pytest

from ops.snap import GallerySnap

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from textual.app import App

##### MATRIX #####
ARCHITECTURES = ("standard", "curves")
_CASES = GallerySnap(ARCHITECTURES).cases()


@pytest.mark.parametrize(("name", "size"), _CASES)
def test_gallery(
    snap_compare: Callable[..., bool],
    gallery_apps: Mapping[str, Callable[[], App[None]]],
    name: str,
    size: tuple[int, int],
) -> None:
    assert GallerySnap.shoot(snap_compare, gallery_apps, name, size)
