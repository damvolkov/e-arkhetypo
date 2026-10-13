"""tests/integration/e_tui/interact/toggle: switches come up lit by defaults-or-previous; commit reports on."""

from textual.widgets import Switch

from e_tui.interact.toggle import Toggle
from e_tui.models.object import Field, ToggleSpec

SPEC = ToggleSpec(
    prompt="pick modules",
    fields=(
        Field(key="rdb", label="Postgres"),
        Field(key="vdb", label="Qdrant"),
        Field(key="req", label="Core", detail="always"),
    ),
    defaults=("rdb",),
    locked=("req",),
)


async def test_toggle_reports_its_defaults_when_untouched(mount) -> None:
    app = mount(lambda: Toggle(SPEC))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.object.commit().values == ("rdb", "req")


async def test_previous_overrides_defaults_on_a_revisit(mount) -> None:
    app = mount(lambda: Toggle(SPEC, previous=("vdb",)))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.object.commit().values == ("vdb", "req")


async def test_clicking_a_switch_changes_the_commit(mount) -> None:
    app = mount(lambda: Toggle(SPEC))
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one("#rdb", Switch).value = False  # the user flips the default off
        await pilot.pause()
        assert app.object.commit().values == ("req",)


async def test_locked_switch_cannot_be_turned_off(mount) -> None:
    app = mount(lambda: Toggle(SPEC))
    async with app.run_test() as pilot:
        await pilot.pause()
        locked = app.query_one("#req", Switch)
        assert locked.disabled
        assert "req" in app.object.commit().values
