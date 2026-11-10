"""tests/unit/e_cli/logic/stores/project/store: the use cases against a bare StorePort — rules at the edge, records inside."""

from typing import TYPE_CHECKING

import pytest

from e_cli.logic.stores.project.store import ProjectStore
from e_cli.models.error import ProjectError
from e_cli.models.project import ProjectState

if TYPE_CHECKING:
    from tests.unit.e_cli.conftest import MemoryStore


async def test_project_create_stores_a_timestamped_record(store: MemoryStore) -> None:
    project = await ProjectStore(store).create("demo", "first", ProjectState.ACTIVE)
    assert project.state is ProjectState.ACTIVE
    assert project.created.tzinfo is not None
    assert (await ProjectStore(store).get("demo")) == project


@pytest.mark.parametrize("name", ["Demo", "d", "demo_1", "x" * 40], ids=["upper", "short", "underscore", "long"])
async def test_project_create_refuses_names_outside_the_slug_rule(store: MemoryStore, name: str) -> None:
    with pytest.raises(ProjectError, match="invalid project"):
        await ProjectStore(store).create(name)


async def test_project_create_refuses_a_long_description(store: MemoryStore) -> None:
    with pytest.raises(ProjectError, match="invalid project"):
        await ProjectStore(store).create("demo", "x" * 121)


async def test_project_listing_streams_every_project(store: MemoryStore) -> None:
    projects = ProjectStore(store)
    for name in ("beta", "alpha"):
        await projects.create(name)
    assert [project.name async for project in projects.listing()] == ["alpha", "beta"]


async def test_project_assign_validates_the_key_and_keeps_the_rest(store: MemoryStore) -> None:
    projects = ProjectStore(store)
    await projects.create("demo")
    await projects.assign("demo", "A", "1")
    project = await projects.assign("demo", "B", "2")
    assert project.env == {"A": "1", "B": "2"}
    with pytest.raises(ProjectError, match="invalid variable name"):
        await projects.assign("demo", "lower", "x")


async def test_project_remove_returns_what_it_deleted(store: MemoryStore) -> None:
    projects = ProjectStore(store)
    await projects.create("demo")
    assert (await projects.remove("demo")).name == "demo"
    with pytest.raises(ProjectError, match="no project named"):
        await projects.get("demo")
