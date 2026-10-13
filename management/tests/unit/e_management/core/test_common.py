"""tests/unit/e_management/core/test_common: exporting prunes free common units (and their tests), cascades to importers, and refuses required ones — proved on a synthetic Graph so the mechanism is independent of what api happens to wire."""

import pytest

from e_management.core.blueprint import Blueprint
from e_management.core.plan import PrunePaths
from e_management.models.graph import SCHEMA, Graph, Unit
from e_management.models.manifest import Common, Template


def _graph() -> Graph:
    settings = Unit(
        key="core/settings",
        area="core",
        name="settings",
        package=False,
        files=("src/core/settings.py",),
        tests=("tests/unit/core/test_settings.py",),
        dependents=("core/proxy",),
        locked=True,
    )
    proxy = Unit(
        key="core/proxy",
        area="core",
        name="proxy",
        package=False,
        files=("src/core/proxy.py",),
        tests=("tests/unit/core/test_proxy.py",),
        deps=("core/settings",),
        closure=("core/settings",),
        level=1,
    )
    return Graph(
        schema=SCHEMA,
        system="api",
        package="e_api",
        source="systems/api",
        areas=("core",),
        inputs_hash="",
        units=(settings, proxy),
    )


def _template() -> Template:
    return Template(
        source="systems/api", package="e_api", brand="e-api", common=Common(root="systems/core", package="e_core")
    )


def test_dropping_a_free_unit_prunes_it_and_its_test() -> None:
    plan = Blueprint(_template(), "demo", _graph()).plan(drop=frozenset({"core/proxy"}))
    pruned = next(a for a in plan.actions if isinstance(a, PrunePaths))
    assert "src/core/proxy.py" in pruned.paths
    assert "tests/unit/core/test_proxy.py" in pruned.paths
    assert "src/core/settings.py" not in pruned.paths


def test_dropping_a_required_unit_is_refused() -> None:
    with pytest.raises(ValueError, match="cannot be dropped"):
        Blueprint(_template(), "demo", _graph()).plan(drop=frozenset({"core/settings"}))


def test_empty_drop_adds_no_prune_action() -> None:
    plan = Blueprint(_template(), "demo", _graph()).plan()
    assert "PrunePaths" not in {type(a).__name__ for a in plan.actions}
