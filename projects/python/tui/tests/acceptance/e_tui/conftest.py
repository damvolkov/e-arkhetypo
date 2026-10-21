"""tests/acceptance/e_tui: the architectures of the snapshot gallery.

Two apps stand in for the language's range: the *standard* template, filled with placeholder slot
content, and *curves*, a showcase where a circle and a hexagon float inside a rectangular stage. The
``gallery_apps`` fixture is the registry the gallery looks up by name; each lookup returns a factory, so
every viewport renders from a fresh instance."""

from typing import TYPE_CHECKING

import pytest
from textual.widgets import Static

from e_tui.app import LayoutApp

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from textual.app import App
from e_tui.layout.spec import Axis, Border, Box, Kind, Line, Measure, Point, Shape
from e_tui.templates.standard import StandardTemplate

##### CURVES SHOWCASE #####
_CURVES = Box(
    id="stage",
    kind=Kind.STATIC,
    border=Border.FINE,
    axis=Axis.ROW,
    padding=1,
    children=(
        Box(
            id="disc",
            kind=Kind.DYNAMIC,
            shape=Shape.CIRCLE,
            border=Border.THICK,
            size=Measure(frac=0.45),
            cross=Measure(frac=0.95),
            offset=Point(x=0.02, y=0.02),
        ),
        Box(
            id="hive",
            kind=Kind.STATIC,
            shape=Shape.POLYGON,
            sides=6,
            border=Border.FINE,
            size=Measure(frac=0.45),
            cross=Measure(frac=0.85),
            offset=Point(x=0.05, y=0.05),
            lines=(Line(text="HEX", emphasis=2),),
        ),
    ),
)


def _standard() -> App[None]:
    """The standard architecture with its three slots filled."""
    return LayoutApp(
        StandardTemplate.SPEC,
        {
            "content": Static("the content field"),
            "steps": Static("1. plan  2. build  3. verify"),
            "keys": Static("esc back · g map · ctrl+r reset · ctrl+q quit"),
        },
    )


def _curves() -> App[None]:
    """The curved-figures showcase: a circle and a hexagon floating in a stage."""
    return LayoutApp(_CURVES, {"disc": Static("●")})


##### REGISTRY #####


@pytest.fixture
def gallery_apps() -> Mapping[str, Callable[[], App[None]]]:
    """Name to factory, the surface the gallery parametrizes and shoots."""
    return {"standard": _standard, "curves": _curves}
