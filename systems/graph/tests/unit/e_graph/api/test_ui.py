"""tests/unit: api.router.ui — the canvas served as a static page, its tunables over the API, the API never shadowed."""

from typing import TYPE_CHECKING

from litestar import Litestar, get
from litestar.testing import TestClient

from core.settings import settings as st
from e_graph.api.router.ui import STATIC, router

if TYPE_CHECKING:
    from pathlib import Path


@get("/topology")
async def topology() -> dict[str, str]:
    return {"route": "api"}


def test_ui_serves_the_bundle_and_yields_to_the_api(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<title>e-graph</title>")
    with TestClient(Litestar([topology, router(tmp_path)])) as client:
        assert client.get("/").text == "<title>e-graph</title>"
        assert client.get("/topology").json() == {"route": "api"}
        assert client.get("/missing.js").status_code == 404


def test_ui_without_a_bundle_is_a_404(tmp_path: Path) -> None:
    with TestClient(Litestar([router(tmp_path / "unbuilt")])) as client:
        assert client.get("/").status_code == 404


def test_ui_default_bundle_lives_in_the_package() -> None:
    assert STATIC.parts[-3:] == ("e_graph", "ui", "dist")


def test_ui_view_reads_the_settings(client) -> None:
    response = client.get("/api/ui")
    assert response.status_code == 200
    assert response.json() == {
        "toast_ms": round(st.ui.ui_toast.total_seconds() * 1000),
        "pace": st.ui.ui_pace.total_seconds(),
        "lane_gap": st.ui.ui_lane_gap,
        "rank_gap": st.ui.ui_rank_gap,
    }
