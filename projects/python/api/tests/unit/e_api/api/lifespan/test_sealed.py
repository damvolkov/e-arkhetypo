"""tests/unit/e_api/api/lifespan/sealed: the last link — the graph read-only once every concern has written its subtree."""

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from litestar.testing import TestClient


def test_sealed_graph_holds_every_section(client: TestClient) -> None:
    assert {"shared", "providers", "engines", "crypto", "mcp"} <= set(client.app.state.system)


def test_sealed_graph_refuses_a_write(client: TestClient) -> None:
    with pytest.raises(RuntimeError, match="Sealed"):
        client.app.state.system.held_by_the_lifespan_only = 1


def test_sealed_graph_refuses_an_unknown_node(client: TestClient) -> None:
    with pytest.raises(AttributeError, match="Sealed state has no node"):
        _ = client.app.state.system.typo_of_a_node
