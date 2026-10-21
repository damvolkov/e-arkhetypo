"""tests/integration/e_tui/app: the wizard walks a graph by keyboard — select, accept, decline, reverse, reset.

The control strip is a one-row hint (three-row buttons would clip it), so navigation is driven through the
bindings; the page's own widgets (a radio, a confirm's yes/no) are exercised directly, not by geometry."""

from collections.abc import Iterable, Mapping

from textual.widgets import Button, RadioButton, Static

from e_tui.app import LayoutApp, WizardApp
from e_tui.flow.graph import Graph
from e_tui.flow.page import Page
from e_tui.models.object import ChoiceSpec, ConfirmSpec, Field, ReportSpec
from e_tui.templates.standard import StandardTemplate


def _flow() -> Graph:
    return Graph(
        "w",
        (
            Page(
                "system",
                "S",
                ChoiceSpec(fields=(Field(key="api", label="API"), Field(key="cli", label="CLI"))),
                produces=frozenset({"system"}),
            ),
            Page("confirm", "C", ConfirmSpec(), requires=frozenset({"system"})),
            Page("report", "R", ReportSpec(lines=("x",))),
        ),
    )


async def _key(pilot, name: str) -> None:
    await pilot.press(name)
    await pilot.pause()


async def _pick(app: WizardApp, pilot, key: str) -> None:
    app.query_one(f"#{key}", RadioButton).value = True
    await pilot.pause()


async def _answer(app: WizardApp, pilot, yes: bool) -> None:
    app.query_one("#yes" if yes else "#no", Button).press()
    await pilot.pause()


async def test_wizard_opens_with_a_hint_and_timeline() -> None:
    app = WizardApp(_flow())
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app._walk.here().id == "system"
        assert str(app.query_one("#steps Static").render()) == "[S]"  # the steps sub-frame survived content's fill
        assert "enter accept" in str(app.query_one("#keys Static").render())


async def test_enter_without_a_choice_leaves_the_walk_put() -> None:
    app = WizardApp(_flow())
    async with app.run_test() as pilot:
        await pilot.pause()
        await _key(pilot, "enter")  # commit() is None while nothing is lit
        assert app._walk.here().id == "system"


async def test_selecting_then_enter_advances_and_moves_the_cursor() -> None:
    app = WizardApp(_flow())
    async with app.run_test() as pilot:
        await pilot.pause()
        await _pick(app, pilot, "api")
        await _key(pilot, "enter")
        assert app._walk.here().id == "confirm"
        assert str(app.query_one("#steps Static").render()) == "S · [C]"


async def test_arrows_and_space_select_a_choice_without_the_mouse() -> None:
    app = WizardApp(_flow())
    async with app.run_test() as pilot:
        await pilot.pause()
        await _key(pilot, "down")  # move the cursor to the second option
        await _key(pilot, "space")  # light it — no mouse
        await _key(pilot, "enter")  # accept the selection
        assert app._walk.here().id == "confirm"
        assert app._walk.state.answers["system"] == ("cli",)


async def test_declining_a_confirm_keeps_the_walk_put() -> None:
    app = WizardApp(_flow())
    async with app.run_test() as pilot:
        await pilot.pause()
        await _pick(app, pilot, "api")
        await _key(pilot, "enter")  # -> confirm
        await _answer(app, pilot, yes=False)  # the object latches ok=False
        await _key(pilot, "enter")  # Declined: the walk stays on confirm
        assert app._walk.here().id == "confirm"


async def test_the_result_view_mounts_when_the_walk_finishes() -> None:
    seen: list[Mapping[str, object]] = []

    def emit(state: Mapping[str, object]) -> Iterable[Static]:
        seen.append(state)
        return [Static("blueprint")]

    app = WizardApp(_flow(), result=emit)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _pick(app, pilot, "api")
        await _key(pilot, "enter")  # -> confirm
        await _answer(app, pilot, yes=True)
        await _key(pilot, "enter")  # -> report
        await _key(pilot, "enter")  # report commits -> Finished -> the host's result view
        assert len(seen) == 1
        assert app._object is None


async def test_reset_returns_to_the_entry_and_back_at_the_head_is_a_no_op() -> None:
    app = WizardApp(_flow())
    async with app.run_test() as pilot:
        await pilot.pause()
        await _pick(app, pilot, "api")
        await _key(pilot, "enter")  # -> confirm
        await _key(pilot, "ctrl+r")  # reset
        assert app._walk.here().id == "system"
        await _key(pilot, "backspace")  # AtFirst: already at the head, nothing changes
        assert app._walk.here().id == "system"


async def test_a_seeded_slot_is_replaced_not_stacked() -> None:
    app = LayoutApp(StandardTemplate.SPEC, {"keys": Static("one")})
    async with app.run_test() as pilot:
        await pilot.pause()
        app.fill("keys", Static("two"))
        await pilot.pause()
        assert len(app.query("#keys Static")) == 1  # cleared by class, sub-frames untouched
