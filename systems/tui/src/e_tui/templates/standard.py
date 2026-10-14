"""e_tui.templates.standard: the standard architecture — the first derivation of the layout language.

Three levels, exactly. The **stage** frames everything and stacks three rows: a **header** band carrying
a pixel masthead (drawn by the house engine, not by plain type), the **content** field that owns the rest
of the screen, and a borderless **keys** strip of a single row where the app's shortcuts live. Floating
inside content, its top band is **steps**: one row for the process trail, inset from the right so the
field reads around it. content, steps and keys are `DYNAMIC` slots a running app fills; stage, header and
the bands' chrome are the constants.

    LayoutApp(StandardTemplate.SPEC, fill={"content": my_widget}).run()
"""

from typing import ClassVar, Final

from e_tui.layout.spec import Axis, Border, Box, Kind, Mast, Measure, Point

##### GEOMETRY #####
_HEADER: Final[float] = 0.22  # header band: a fifth of the stage, masthead scaled to fit
_MAST: Final[float] = 0.3  # the bitmap may claim up to this share of the terminal
_STEPS: Final[float] = 0.92  # the steps band stops before the right edge of its field


class StandardTemplate:
    """The standard frame: pixel header, content field with a one-row steps band, thin keys strip."""

    SPEC: ClassVar[Box] = Box(
        id="stage",
        kind=Kind.STATIC,
        border=Border.FINE,
        axis=Axis.COLUMN,
        padding=1,
        children=(
            Box(
                id="header",
                kind=Kind.STATIC,
                border=Border.FINE,
                padding=1,
                size=Measure(frac=_HEADER, min_cells=6),
                mast=Mast(main="E-TUI", sub="eager series", max_height=_MAST),
            ),
            Box(
                id="content",
                kind=Kind.DYNAMIC,
                border=Border.FINE,
                axis=Axis.OVERLAY,
                padding=1,
                size=Measure(weight=1.0, min_cells=4),
                children=(
                    Box(
                        id="steps",
                        kind=Kind.DYNAMIC,
                        border=Border.FINE,
                        size=Measure(frac=_STEPS),
                        cross=Measure(frac=0.0, min_cells=1, max_cells=1),  # a single row
                        offset=Point(x=0.04, y=0.04),
                    ),
                ),
            ),
            Box(
                id="keys",
                kind=Kind.DYNAMIC,
                border=Border.NONE,
                padding=0,
                size=Measure(frac=0.0, min_cells=1, max_cells=1),  # the thin independent strip
            ),
        ),
    )
