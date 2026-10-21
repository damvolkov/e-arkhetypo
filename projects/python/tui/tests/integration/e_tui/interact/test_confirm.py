"""tests/integration/e_tui/interact/confirm: silence commits nothing; yes and no fork the answer."""

from textual.widgets import Button

from e_tui.interact.confirm import Confirm
from e_tui.models.object import ConfirmSpec


def _press(app, button_id: str) -> None:
    """Drive the confirm's handler with a synthetic button press."""
    host = app.object
    host.on_button_pressed(Button.Pressed(app.query_one(f"#{button_id}", Button)))  # type: ignore[attr-defined]


async def test_an_unanswered_confirm_commits_nothing(mount) -> None:
    app = mount(lambda: Confirm(ConfirmSpec(prompt="go?", detail="this writes files")))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.object.commit() is None


async def test_yes_commits_an_accepted_answer(mount) -> None:
    app = mount(lambda: Confirm(ConfirmSpec(prompt="go?")))
    async with app.run_test() as pilot:
        await pilot.pause()
        _press(app, "yes")
        assert app.object.commit().ok


async def test_no_commits_a_refusal(mount) -> None:
    app = mount(lambda: Confirm(ConfirmSpec()))
    async with app.run_test() as pilot:
        await pilot.pause()
        _press(app, "no")
        assert app.object.commit().ok is False
