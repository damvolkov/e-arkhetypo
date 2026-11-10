"""tests/unit/e_api/api/state: Litestar's own state class, typed, installed by the composition root — and law 22, checked:
the attribute chain of the sealed system is the module path.

The real lifespan chain fills and seals the system; the whole tree is walked. Every node whose class is a stratum's
lives in the package its chain names: a `system.logic.store` in `e_api.logic.store`. Tools (ops, providers, engines,
processors, infra's wrappers, builtins, mappings, third parties) are no node of a stratum; the infrastructure sections
(`shared`, `providers`, `engines`) are walked, their own classes never placed. The blueprint mounts no stratum yet: the
gate holds for the first one a project adds. And one object, one path: nothing the system holds lives at two."""

from typing import TYPE_CHECKING

import pytest
from litestar import Litestar

from e_api.api.state import AppState
from e_api.infra.state import State
from e_api.main import create_app

if TYPE_CHECKING:
    from litestar.testing import TestClient


def test_state_create_app_installs_the_typed_state() -> None:
    app = create_app()
    assert type(app.state) is AppState
    assert isinstance(AppState.of(app).system, State)


def test_state_of_refuses_a_foreign_state() -> None:
    with pytest.raises(TypeError, match="not AppState"):
        AppState.of(Litestar())


async def test_state_reserved_state_kwarg_builds_the_typed_class(client: TestClient) -> None:
    """What Litestar injects for `state: AppState`: the subclass, over the same entries — the same system."""
    injected = AppState(client.app.state)
    assert injected.system is client.app.state.system


def test_state_every_node_lives_in_the_package_its_path_names(held: list[tuple[str, str]]) -> None:
    assert [(chain, module) for chain, module in held if not module.startswith(f"e_api.{chain}")] == []


def test_state_no_object_lives_at_two_paths(twins: list[list[str]]) -> None:
    assert twins == []
