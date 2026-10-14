"""tests/unit/e_management/ui/graph_html: the map renderer that `make map` writes to the temp dir."""

from e_management.cli.commands import dependency_map
from e_management.ui.view import render_map_html


def test_render_map_html_carries_every_unit_and_edge(repo, spec) -> None:
    graph = dependency_map(repo, spec, "api")
    assert graph is not None
    html = render_map_html([("api", graph)])
    assert "graph BT" in html
    assert "mermaid" in html
    assert all(f'["{u.key}' in html for u in graph.units)
    assert "-->" in html


def test_render_map_html_over_two_systems(repo, spec) -> None:
    api, cli = dependency_map(repo, spec, "api"), dependency_map(repo, spec, "cli")
    assert api is not None
    assert cli is not None
    html = render_map_html([("api", api), ("cli", cli)])
    assert "<h2>api</h2>" in html
    assert "<h2>cli</h2>" in html
