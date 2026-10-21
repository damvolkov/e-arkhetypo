"""e_tui.layout.spec: the geometry language — a config file, YAML/TOML/JSON, becomes a fillable box tree.

The layout mini-framework speaks one type, `Box`: a shape placed inside its parent, holding either static
text (`STATIC`) or a named slot a running app fills at runtime (`DYNAMIC`). A spec is pure geometry and
intent, never a widget: it crosses the trust boundary (a file), so it is a validated `msgspec.Struct`;
`e_tui.layout.render` turns it into Textual containers. Nothing here imports or knows Textual.

Measures are **relative**: every size is a fraction of the parent (0..1) with optional cell clamps, so the
tree stays responsive when the terminal resizes. Depth is capped at three boxes (root, child, grandchild)
so the language never becomes a scene graph. The figures are basic: rectangles, ellipses and polygons —
regular (`sides`) or irregular (`points`).

    spec = Box.load(Path("standard.yml"))   # decode + validate + reject bad geometry
    slots = spec.slots()                    # {id: box} for every DYNAMIC box, for the app to fill
"""

from collections.abc import Iterator
from enum import StrEnum
from pathlib import Path
from typing import Final

import eserde
import msgspec

from e_tui.models.error import SpecError

##### LIMITS #####
MAX_DEPTH: Final[int] = 3
MIN_SIDES: Final[int] = 3  # the simplest closed figure
MAX_SIDES: Final[int] = 8  # basic figures only: a polygon is bounded, not a path editor
EMPHASIS: Final[frozenset[int]] = frozenset({0, 1, 2})  # 0 body · 1 sub-header · 2 headline

##### VOCABULARY #####


class Kind(StrEnum):
    """Whether a box carries its own content or waits for the app to fill it."""

    STATIC = "static"  # only letters live here: a header, a caption
    DYNAMIC = "dynamic"  # a named slot, empty until an app mounts widgets into it


class Shape(StrEnum):
    """The base figures the language admits — nothing more exotic."""

    RECT = "rect"
    ELLIPSE = "ellipse"
    CIRCLE = "circle"
    POLYGON = "polygon"


class Border(StrEnum):
    """Edge treatment: `THICK` a heavy outline, `FILL` the box painted solid."""

    NONE = "none"
    FINE = "fine"
    THICK = "thick"
    FILL = "fill"


class Axis(StrEnum):
    """How a box arranges its children inside itself."""

    ROW = "row"  # horizontal split, main axis left-to-right
    COLUMN = "column"  # vertical split, main axis top-to-bottom
    OVERLAY = "overlay"  # children float, each placed by its own offset


##### NODES #####


class Measure(msgspec.Struct, frozen=True, kw_only=True, omit_defaults=True):
    """A size along one axis: a fraction of the parent plus optional cell clamps.

    Relative by law — `frac` is what scales with the terminal; `min_cells`/`max_cells` keep a frame
    legible and bounded. `weight` only matters inside a flow (`ROW`/`COLUMN`), where fr-units share
    the leftover space."""

    frac: float = 1.0
    weight: float = 0.0
    min_cells: int = 0
    max_cells: int | None = None


class Point(msgspec.Struct, frozen=True, omit_defaults=True):
    """A normalized coordinate inside a box: fractions of its width and height."""

    x: float = 0.0
    y: float = 0.0


class Line(msgspec.Struct, frozen=True, kw_only=True, omit_defaults=True):
    """One row of a STATIC box: text plus an emphasis level."""

    text: str
    emphasis: int = 0


class Mast(msgspec.Struct, frozen=True, kw_only=True, omit_defaults=True):
    """A pixel masthead a STATIC box carries instead of lines: a bitmap title and its tagline.

    The language declares *that* a box shows a masthead; how the pixels are drawn belongs to
    `ops.tui.HeaderTui`, the house engine. `max_height` bounds the artwork as a fraction of the
    terminal, so a resize shrinks the bitmap in integer steps and never overflows the box."""

    main: str
    sub: str = ""
    max_height: float = 0.35


class Box(msgspec.Struct, frozen=True, kw_only=True, omit_defaults=True):
    """A shape inside its parent: geometry, treatment, and either static lines or child boxes.

    A leaf is `STATIC` with `lines`, or `DYNAMIC` waiting to be filled — an `id` makes a dynamic box a
    named slot. A branch arranges its `children` by `axis`. Ids, when present, are unique in the tree."""

    id: str | None = None
    kind: Kind = Kind.STATIC
    shape: Shape = Shape.RECT
    border: Border = Border.FINE
    axis: Axis = Axis.OVERLAY
    size: Measure = msgspec.field(default_factory=Measure)
    cross: Measure = msgspec.field(default_factory=Measure)
    offset: Point = Point()
    padding: int = 0
    sides: int = 0  # regular polygon: an n-gon inscribed in the box, 3..MAX_SIDES
    points: tuple[Point, ...] = ()  # irregular polygon: its vertices, given it overrides `sides`
    lines: tuple[Line, ...] = ()
    mast: Mast | None = None  # STATIC only, in place of lines: a pixel masthead
    children: tuple["Box", ...] = ()

    def __post_init__(self) -> None:
        """Reject any geometry the renderer could not honor, before it ever reaches a widget."""
        _require(not self.lines or self.kind is Kind.STATIC, "only a static box may hold lines")
        _require(self.mast is None or self.kind is Kind.STATIC, "only a static box may carry a masthead")
        _require(self.mast is None or not self.lines, "a masthead box shows the masthead, not lines")
        _require(all(line.emphasis in EMPHASIS for line in self.lines), f"emphasis must be in {sorted(EMPHASIS)}")
        _require(_frac(self.size) and _frac(self.cross), "frac must lie in [0, 1]")
        _require(self.size.min_cells >= 0 and self.cross.min_cells >= 0, "min_cells must be >= 0")
        _require(_clamped(self.size) and _clamped(self.cross), "max_cells must not undercut min_cells")
        _require(_frac(self.offset) and self.padding >= 0, "offset must lie in [0, 1] and padding be >= 0")
        _require(
            self.shape is not Shape.POLYGON or _regular(self) or _irregular(self), "polygon needs 3..8 sides or points"
        )
        _require(self.shape is Shape.POLYGON or not (self.sides or self.points), "sides/points belong to a polygon")
        _require(all(_frac(point) for point in self.points), "polygon points must lie in [0, 1]")
        _check_tree(self)

    ##### VIEWS #####

    def walk(self) -> Iterator[Box]:
        """Yield self and every descendant, parents before children."""
        yield self
        for child in self.children:
            yield from child.walk()

    def slots(self) -> dict[str, Box]:
        """The fillable boxes, keyed by id — the contract between a spec and the app that fills it."""
        return {box.id: box for box in self.walk() if box.id is not None and box.kind is Kind.DYNAMIC}

    ##### LOAD #####

    @classmethod
    def load(cls, path: Path) -> Box:
        """Decode a spec file (YAML/TOML/JSON, inferred by extension) into a validated tree.

        e-serde infers the format from the extension and drives the decode with `type=`, so a
        missing, malformed or illegal file surfaces as one `SpecError` naming the path."""
        bad = f"{path.name}: not a valid layout spec"
        try:
            return eserde.load(path, type=cls)
        except (eserde.CodecError, eserde.LoadError, msgspec.ValidationError, OSError) as error:
            raise SpecError(f"{bad}: {error}") from error  # noqa: EM102 — the load message wraps the codec's own


##### VALIDATION #####


def _frac(point: Point | Measure) -> bool:
    """True when both axes of `point` (or the `frac` of a `Measure`) lie inside [0, 1]."""
    values = (point.frac,) if isinstance(point, Measure) else (point.x, point.y)
    return all(0.0 <= value <= 1.0 for value in values)


def _clamped(measure: Measure) -> bool:
    """True unless a max_cells clamp contradicts its min_cells floor."""
    return measure.max_cells is None or measure.max_cells >= measure.min_cells


def _regular(box: Box) -> bool:
    """True when a polygon is well-formed by side count."""
    return MIN_SIDES <= box.sides <= MAX_SIDES and not box.points


def _irregular(box: Box) -> bool:
    """True when a polygon is well-formed by explicit vertices."""
    return not box.sides and MIN_SIDES <= len(box.points) <= MAX_SIDES


def _require(holds: bool, why: str) -> None:  # noqa: FBT001 — the boolean argument IS the predicate
    """Raise `SpecError(why)` when `holds` is false."""
    if not holds:
        raise SpecError(why)


def _check_tree(root: Box) -> None:
    """Enforce the whole-tree invariants a single node cannot see: the depth cap and id uniqueness."""
    deep = f"the tree may not nest deeper than {MAX_DEPTH} levels"
    _require(_depth(root) <= MAX_DEPTH, deep)
    seen: set[str] = set()
    for box in root.walk():
        dupe = f"duplicate slot id: {box.id!r}"
        if box.id is not None:
            _require(box.id not in seen, dupe)
            seen.add(box.id)


def _depth(box: Box) -> int:
    """Levels from `box` down to its deepest leaf (a leaf has depth 1)."""
    return 1 + max((_depth(child) for child in box.children), default=0)
