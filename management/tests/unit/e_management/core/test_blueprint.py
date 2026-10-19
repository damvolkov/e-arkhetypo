"""tests/unit/e_management/core/blueprint: name validation, choice composition and the ordering of the emitted plan."""

import pytest

from e_management.core.blueprint import Blueprint
from e_management.core.errors import (
    ChoiceDependencyError,
    InvalidNameError,
    MandatoryCollisionError,
    UnknownChoiceError,
)
from e_management.core.plan import Copy, Plan, PrunePaths, Rename
from e_management.models.manifest import Choice, Group, Template

SYNTH = Template(
    source="systems/api",
    package="e_api",
    brand="e-api",
    choices=(
        Choice(name="redis", group=Group.STACK),
        Choice(name="user", group=Group.MODULES, requires=("redis",)),
    ),
    mandatory=("tests/keep_me.py",),
)


def test_blueprint_derives_package_and_brand() -> None:
    blueprint = Blueprint(SYNTH, "myapp")
    assert (blueprint.package, blueprint.brand) == ("e_myapp", "e-myapp")


def test_blueprint_rejects_names_that_are_not_slugs() -> None:
    for bad in ("My_App", "9x", "-x", "", "a-b"):
        with pytest.raises(InvalidNameError):
            Blueprint(SYNTH, bad)


def test_blueprint_rejects_undeclared_choices() -> None:
    with pytest.raises(UnknownChoiceError):
        Blueprint(SYNTH, "myapp").plan(frozenset({"gpu"}))


def test_blueprint_enforces_choice_dependencies() -> None:
    with pytest.raises(ChoiceDependencyError):
        Blueprint(SYNTH, "myapp").plan(frozenset({"redis"}))


def test_blueprint_keeps_choices_without_requires() -> None:
    assert [c.name for c in Blueprint(SYNTH, "myapp").on(frozenset({"user"}))] == ["redis"]


def test_blueprint_groups_and_defaults() -> None:
    blueprint = Blueprint(SYNTH, "myapp")
    assert [c.name for c in blueprint.choices(Group.MODULES)] == ["user"]
    assert blueprint.choices(Group.CICD) == ()
    assert blueprint.defaults_off == frozenset()
    sparse = Template(
        source="s", package="e_s", brand="e-s", choices=(Choice(name="beta", group=Group.STACK, default=False),)
    )
    assert Blueprint(sparse, "x").defaults_off == frozenset({"beta"})


def test_blueprint_rejects_choices_touching_mandatory() -> None:
    clash = Template(
        source="systems/api",
        package="e_api",
        brand="e-api",
        choices=(Choice(name="naughty", group=Group.MODULES, paths=("tests/keep_me.py",)),),
        mandatory=("tests/keep_me.py",),
    )
    with pytest.raises(MandatoryCollisionError):
        Blueprint(clash, "myapp").plan()


def test_plan_orders_copy_materialize_prune_rename_finalize(spec) -> None:
    plan: Plan = Blueprint(spec.templates["api"], "myapp").plan(frozenset({"websockets"}))
    kinds = tuple(type(a).__name__ for a in plan.actions)
    assert kinds[0] == "Copy"
    assert kinds[1] == "Materialize"
    assert kinds.index("PrunePaths") < kinds.index("Rename")
    assert kinds[-1] == "PruneTexts"
    rename = next(a for a in plan.actions if isinstance(a, Rename))
    assert {(r.frm, r.to) for r in rename.rules} == {("e_api", "e_myapp"), ("e-api", "e-myapp")}


def test_plan_full_selection_has_no_prunes(spec) -> None:
    plan = Blueprint(spec.templates["api"], "myapp").plan()
    assert not any(isinstance(a, PrunePaths) for a in plan.actions)
    assert isinstance(plan.actions[0], Copy)
    assert plan.actions[0].drops == (
        "uv.lock",
        "scripts/materialize.py",
        ".github/workflows",
        ".github/ci.map.yml",
        ".github/ci.vars.example",
        ".github/INSTALL.md",
        "tests/unit/test_ci_contract.py",
    )
