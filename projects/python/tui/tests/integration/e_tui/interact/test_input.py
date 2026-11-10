"""tests/integration/e_tui/interact/input: a blank line never commits; previous text restores."""

from typing import TYPE_CHECKING

from textual.widgets import Input

from e_tui.interact.input import TextInput
from e_tui.models.object import InputSpec

if TYPE_CHECKING:
    from tests.integration.e_tui.interact.conftest import Mounter

SPEC = InputSpec(prompt="name", placeholder="my-project")


async def test_blank_line_is_not_an_answer(mount: Mounter) -> None:
    app = mount(lambda: TextInput(SPEC))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.object.commit() is None


async def test_typed_text_commits_trimmed(mount: Mounter) -> None:
    app = mount(lambda: TextInput(SPEC))
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one(Input).value = "  eager  "
        assert app.object.commit().values == ("eager",)


async def test_previous_text_is_restored(mount: Mounter) -> None:
    app = mount(lambda: TextInput(SPEC, previous=("kept",)))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.object.commit().values == ("kept",)


async def test_secret_spec_masks_the_line(mount: Mounter) -> None:
    app = mount(lambda: TextInput(InputSpec(secret=True)))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one(Input).password
