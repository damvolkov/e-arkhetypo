"""api.router.ui: the canvas edge — its static page at `/`, its tunables at `/api/ui`.

The canvas is part of the package: its TypeScript lives in `e_graph/ui/`, `make bundle` compiles it
into `e_graph/ui/dist/` (generated, never committed, shipped in the wheel) and the app serves that with
`html_mode`, so `/` is the canvas and every API route still wins by
specificity. No bundle, no page: `/` answers 404 and the API runs untouched. The page is static, so
its tunables come from the API like everything else it shows: `UI_*` settings, read at call time."""

from pathlib import Path
from typing import Final

from litestar import get
from litestar.handlers import HTTPRouteHandler
from litestar.router import Router
from litestar.static_files import create_static_files_router

from e_graph.models.ui import UiView
from infra.settings import settings as st

UI: Final[Path] = Path(__file__).resolve().parents[2] / "ui"
STATIC: Final[Path] = UI / "dist"
MS_PER_SECOND: Final[int] = 1000


async def view() -> UiView:
    """The canvas tunables, in the units it draws with: milliseconds, seconds of pace, pixels."""
    return UiView(
        toast_ms=round(st.ui.toast.total_seconds() * MS_PER_SECOND),
        pace=st.ui.pace.total_seconds(),
        lane_gap=st.ui.lane_gap,
        rank_gap=st.ui.rank_gap,
    )


ROUTES: tuple[HTTPRouteHandler, ...] = (get("/api/ui", name="ui.view")(view),)


def router(directory: Path = STATIC) -> Router:
    """The static canvas mounted at `/`; the directory is a parameter so a test can serve its own bundle."""
    return create_static_files_router(path="/", directories=[directory], html_mode=True, name="ui")
