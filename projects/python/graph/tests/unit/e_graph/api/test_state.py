"""tests/unit: api.state — Litestar's own state class, typed, installed by the composition root."""

import pytest
from litestar import Litestar

from e_graph.api.state import AppState
from e_graph.main import create_app
from infra.state import State


def test_create_app_installs_the_typed_state() -> None:
    app = create_app()
    assert type(app.state) is AppState
    assert isinstance(AppState.of(app).system, State)


def test_of_refuses_a_foreign_state() -> None:
    with pytest.raises(TypeError, match="not AppState"):
        AppState.of(Litestar())


async def test_reserved_state_kwarg_builds_the_typed_class(client) -> None:
    """What Litestar injects for `state: AppState`: the subclass, over the same entries — the same system."""
    injected = AppState(client.app.state)
    assert injected.system is client.app.state.system
