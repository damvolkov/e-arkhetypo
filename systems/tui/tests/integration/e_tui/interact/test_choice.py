"""tests/integration/e_tui/interact/choice: one radio answers, or the step is still open."""

from textual.widgets import RadioButton

from e_tui.interact.choice import Choice
from e_tui.models.object import ChoiceSpec, Field

SPEC = ChoiceSpec(prompt="pick api", fields=(Field(key="rest", label="REST"), Field(key="grpc", label="gRPC")))


async def test_choice_is_unanswered_until_a_button_lights(mount) -> None:
    app = mount(lambda: Choice(SPEC))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.object.commit() is None


async def test_choice_prefers_previous_over_the_declared_selection(mount) -> None:
    spec = ChoiceSpec(fields=SPEC.fields, selected="rest")
    app = mount(lambda: Choice(spec, previous=("grpc",)))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.object.commit().values == ("grpc",)


async def test_choice_falls_back_to_the_declared_selection(mount) -> None:
    app = mount(lambda: Choice(ChoiceSpec(fields=SPEC.fields, selected="rest")))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.object.commit().values == ("rest",)


async def test_clicking_a_radio_changes_the_commit(mount) -> None:
    app = mount(lambda: Choice(SPEC))
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one("#grpc", RadioButton).value = True
        await pilot.pause()
        assert app.object.commit().values == ("grpc",)
