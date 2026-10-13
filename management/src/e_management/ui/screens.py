"""ui.screens: thin forms over the session — one decision per stage, saved to the draft; back never destroys what still holds."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from msgspec import UNSET
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Input, Static

from e_management.core.errors import ManagementError
from e_management.core.session import Step
from e_management.models.manifest import Group
from e_management.ui.view import render_graph, render_plan, render_trail
from ops.tui import HeaderTui

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from textual.app import ComposeResult

    from e_management.models.manifest import Choice
    from e_management.ui.app import ManagementApp

##### DEFAULTS #####
MASTHEAD: float = 0.35  # the header grows up to this share of the terminal height, never more
MARK: dict[str, str] = {"on": "●", "off": "○", "locked": "◆"}


##### TYPES #####
@dataclass(frozen=True, slots=True)
class Tile:
    """One switchable item of a stage: its key, what it shows, and whether the user may flip it."""

    key: str
    title: str
    detail: str = ""
    locked: bool = False


class Section(Static):
    """One-line heading inside the stage box: the family (COMMON/SYSTEM) and the member."""

    DEFAULT_CSS = """
    Section { text-style: bold; color: #6f9bff; }
    """


class WizardScreen(Screen[None]):
    """Shared plumbing: masthead, step trail, stage box, footer, typed app, error line and the draft-saving confirmation."""

    STEP: str = ""

    @property
    def management(self) -> ManagementApp:
        return cast("ManagementApp", self.app)

    def compose(self) -> ComposeResult:
        yield HeaderTui(max_height=MASTHEAD)
        session = self.management.session
        yield Static(render_trail(self.management.flow(), session.seen, self.STEP), id="trail")
        with Vertical(id="stage"):
            yield from self.body()
        yield Footer()

    def fail(self, message: str) -> None:
        self.query_one("#error", Static).update(f"✗ {message}")

    def mark(self, step: str) -> None:
        """Confirm a stage: recorded in the session and persisted — the unit of the wizard's memory."""
        self.management.session.seen = (*self.management.session.seen, step)
        self.management.save_draft()

    def body(self) -> ComposeResult:
        """The stage's own widgets."""
        raise NotImplementedError
        yield


class ToggleScreen(WizardScreen):
    """A stage of ON/OFF tiles: each item is a ``Tile``; the flow is a class fact."""

    FAMILY = "SYSTEM"
    HINT = "click a tile to switch it  ·  ● on   ○ off   ◆ goes with what needs it"

    def items(self) -> Iterator[Tile]:
        raise NotImplementedError
        yield

    def switched_off(self) -> set[str]:
        raise NotImplementedError

    def commit(self, off: set[str]) -> None:
        raise NotImplementedError

    def toggle(self, key: str) -> set[str]:
        """The switched-off set after flipping ``key`` — overridable by stages with dependencies."""
        return self.switched_off() ^ {key}

    def refusal(self, tile: Tile) -> str:
        """Why a locked tile will not switch."""
        return f"{tile.title} {tile.detail} — it stays"

    def next_screen(self) -> Screen:
        return self.management.advance(self.STEP)

    @staticmethod
    def tile_id(key: str) -> str:
        return "tile-" + key.replace("/", "-")

    @staticmethod
    def tile_key(tile_id: str) -> str:
        return tile_id.removeprefix("tile-").replace("-", "/")

    def body(self) -> ComposeResult:
        yield Section(f"{self.FAMILY} · {self._member()}")
        yield Static(self.HINT, classes="hint")
        with Grid(classes="tiles"):
            for tile in self.items():
                yield Button(self._label(tile), id=self.tile_id(tile.key), classes=self._tile_classes(tile))
        yield Static("", id="error", classes="error")
        with Horizontal(classes="actions"):
            yield Button("continue  →", id="next", variant="primary")

    def _state(self, tile: Tile) -> str:
        return "locked" if tile.locked else "off" if tile.key in self.switched_off() else "on"

    def _label(self, tile: Tile) -> str:
        return f"{MARK[self._state(tile)]}  {tile.title}\n[dim]   {tile.detail}[/]"

    def _tile_classes(self, tile: Tile) -> str:
        return f"tile -{self._state(tile)}"

    def _member(self) -> str:
        return self.STEP

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if not event.button.id.startswith("tile-"):
            self._advance()
            return
        tile = next(item for item in self.items() if item.key == self.tile_key(event.button.id))
        if tile.locked:
            self.fail(self.refusal(tile))
            return
        try:
            self.commit(self.toggle(tile.key))
        except ValueError as exc:
            self.fail(str(exc))
            return
        self.query_one("#error", Static).update("")
        self.management.save_draft()
        tiles = {item.key: item for item in self.items()}
        for button in self.query(".tile").results(Button):
            fresh = tiles[self.tile_key(button.id)]
            button.label = self._label(fresh)
            button.set_classes(self._tile_classes(fresh))

    def _advance(self) -> None:
        app = self.management
        try:
            app.plan()
        except (ManagementError, ValueError) as exc:
            self.fail(str(exc))
        else:
            self.mark(self.STEP)
            self.app.push_screen(self.next_screen())


class SystemScreen(WizardScreen):
    """Stage 1: pick the template and name the project — the name is validated by the domain's own Blueprint."""

    STEP = Step.SYSTEM

    def body(self) -> ComposeResult:
        app = self.management
        stored = app.session.name
        yield Section("SYSTEM · choose")
        yield Static("pick a template, then name the project and press enter", classes="hint")
        with Grid(classes="tiles"):
            for name in sorted(app.spec.templates):
                yield Button(self._label(name), id=f"template-{name}", classes=self._tile_classes(name))
        yield Static("name  ·  lowercase, digits, underscores", classes="label")
        yield Input(placeholder="myapp", value="" if stored is UNSET else str(stored), id="name")
        yield Static("", id="error", classes="error")

    def _label(self, name: str) -> str:
        source = self.management.spec.templates[name].source
        return f"{MARK['on' if name == self.management.session.template else 'off']}  {name}\n[dim]   {source}[/]"

    def _tile_classes(self, name: str) -> str:
        return f"tile -{'on' if name == self.management.session.template else 'off'}"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        app = self.management
        app.session.template = event.button.id.removeprefix("template-")
        app.save_draft()
        for button in self.query(".tile").results(Button):
            name = button.id.removeprefix("template-")
            button.label = self._label(name)
            button.set_classes(self._tile_classes(name))
        self.query_one("#name", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        app = self.management
        if app.session.template is UNSET:
            self.fail("pick a template first")
            return
        try:
            app.blueprint(event.value)
        except ManagementError as exc:
            self.fail(str(exc))
        else:
            app.session.name = event.value
            app.begin_flow()
            self.mark(Step.SYSTEM)
            self.app.push_screen(app.advance(Step.SYSTEM))


class CommonAreaScreen(ToggleScreen):
    """One stage per discovered COMMON area: a tile per unit, ON by default, dropping cascades over dependents."""

    FAMILY = "COMMON"

    def __init__(self, area: str) -> None:
        super().__init__()
        self.STEP = f"common-{area}"
        self.area = area

    def _member(self) -> str:
        return self.area

    def items(self) -> Iterator[Tile]:
        graph = self.management.dependency_map()
        drop = frozenset(self.management.session.drop)
        for unit in graph.in_area(self.area):
            needers = sorted(key.rsplit("/", 1)[-1] for key in graph.needed_by(unit.key, drop))
            tests = len(unit.tests)
            detail = (
                f"needed by {', '.join(needers)}"
                if needers
                else "wired by the system"
                if unit.key in graph.required
                else f"{tests} test{'s' * (tests != 1)}"
            )
            yield Tile(key=unit.key, title=unit.name, detail=detail, locked=graph.locked(unit.key, drop))

    def switched_off(self) -> set[str]:
        return set(self.management.session.drop)

    def commit(self, off: set[str]) -> None:
        self.management.session.drop = tuple(sorted(self.management.dependency_map().cascade(frozenset(off))))

    def toggle(self, key: str) -> set[str]:
        """Off drops ``key``; on brings back ``key`` and everything it imports — a unit never arrives without its base."""
        off = self.switched_off()
        return off - {key, *self.management.dependency_map().requires(key)} if key in off else off | {key}


class ChoiceAreaScreen(ToggleScreen):
    """A stage over the template's declared choices of one group (modules, infra, cicd)."""

    GROUPS: tuple[Group, ...] = ()

    def __init__(self, step: str = "modules") -> None:
        super().__init__()
        self.STEP = step

    def _member(self) -> str:
        return self.STEP

    def choices(self) -> tuple[Choice, ...]:
        app = self.management
        declared = app.spec.templates[str(app.session.template)].choices
        return tuple(choice for choice in declared if choice.group in self.GROUPS)

    def items(self) -> Iterator[Tile]:
        for choice in self.choices():
            yield Tile(key=choice.name, title=choice.name, detail=choice.label, locked=False)

    def switched_off(self) -> set[str]:
        return set(self.management.session.off)

    def commit(self, off: set[str]) -> None:
        self.management.session.off = tuple(sorted(off))


class ConfirmScreen(WizardScreen):
    """Final stage: destination, unit tests post-export, the full plan — algorithms run only on generate."""

    STEP = "confirm"

    def body(self) -> ComposeResult:
        app = self.management
        stored = app.session.dest
        yield Section("SYSTEM · confirm")
        yield Static("destination  ·  empty keeps the suggestion", classes="label")
        yield Input(value="" if stored is UNSET else str(stored), placeholder=str(app.suggested()), id="dest")
        with VerticalScroll(id="planbox"):
            yield Static(self._plan_text(), id="plan")
        yield Static("", id="error", classes="error")
        with Horizontal(classes="actions"):
            yield Button(self._tests_label(), id="tests", classes=self._tests_tile_classes())
            yield Button("generate  →", id="go", variant="primary")

    def _tests_label(self) -> str:
        return f"{MARK['on' if self.management.session.verify_tests else 'off']}  unit tests after export"

    def _tests_tile_classes(self) -> str:
        return f"tile -{'on' if self.management.session.verify_tests else 'off'}"

    def on_input_submitted(self, event: Input.Submitted) -> None:  # noqa: ARG002 — the signature is the message contract
        self._take_dest()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        app = self.management
        match event.button.id:
            case "tests":
                app.session.verify_tests = not app.session.verify_tests
                app.save_draft()
                button = self.query_one("#tests", Button)
                button.label = self._tests_label()
                button.set_classes(self._tests_tile_classes())
            case "go":
                self._generate()

    def _take_dest(self) -> Path | None:
        app = self.management
        field = self.query_one(Input)
        app.session.dest = str(app.suggested() if not field.value else field.value)
        try:
            app.check_target(app.session.target())
        except OSError as exc:
            self.fail(str(exc))
            return None
        return app.session.target()

    def _generate(self) -> None:
        app = self.management
        if self._take_dest() is not None and (plan := app.plan()) is not None:
            self.mark("confirm")
            app.start_generate(plan)

    def _plan_text(self) -> str:
        app = self.management
        try:
            plan = app.plan()
        except (ManagementError, ValueError) as exc:
            return f"stale session: {exc}"
        return render_plan(plan)


class ProgressScreen(WizardScreen):
    """The pipeline's log: every emitted line of every step, streaming while generation and verification run."""

    STEP = "confirm"

    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def body(self) -> ComposeResult:
        yield Section("SYSTEM · generating")
        yield Static("ctrl+q quits; the draft survives", classes="hint")
        with VerticalScroll(id="planbox"):
            yield Static("", id="log")

    async def line(self, text: str) -> None:
        self.lines.append(text)
        self.query_one("#log", Static).update("\n".join(self.lines))
        self.query_one("#planbox", VerticalScroll).scroll_end(animate=False)


class ReportScreen(WizardScreen):
    """The verdict: ready to work — or the failed steps, verbatim, with a way back to fix and retry."""

    STEP = "confirm"

    def __init__(self, *, ok: bool, dest: Path, failures: list[str]) -> None:
        super().__init__()
        self.ok, self.dest, self.failures = ok, dest, failures

    def body(self) -> ComposeResult:
        yield Section(f"SYSTEM · {'ready' if self.ok else 'stopped'}")
        verdict = (
            f"✓ {self.dest} is ready to work — cd in and start"
            if self.ok
            else "✗ stopped:\n" + "\n".join(self.failures[-40:])
        )
        with VerticalScroll(id="planbox"):
            yield Static(verdict, id="verdict")
        with Horizontal(classes="actions"):
            yield (
                Button("finish", id="finish", variant="primary")
                if self.ok
                else Button("←  back to review", id="retry", variant="warning")
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        match event.button.id:
            case "finish":
                self.app.exit()
            case _:
                self.app.pop_screen()


class DependencyScreen(Screen[None]):
    """A read-only inspector of the live dependency map, opened with `g` — never a step of the wizard."""

    @property
    def management(self) -> ManagementApp:
        return cast("ManagementApp", self.app)

    def compose(self) -> ComposeResult:
        yield HeaderTui(max_height=MASTHEAD)
        with Vertical(id="stage"):
            chosen = self.management.session.template
            yield Section("GRAPH · " if chosen is UNSET else f"GRAPH · {chosen}")
            yield Static("read-only  ·  AST imports + graphlib levels  ·  esc to go back", classes="hint")
            with VerticalScroll(id="planbox"):
                yield Static(render_graph(self.management.graph()), id="map")
        yield Footer()


class ModulesScreen(ChoiceAreaScreen):
    """The functional modules the service itself ships with."""

    def __init__(self) -> None:
        super().__init__("modules")
        self.GROUPS = (Group.MODULES,)


class OptionsScreen(ChoiceAreaScreen):
    """Infrastructure and CI/CD surfaces of the service."""

    def __init__(self) -> None:
        super().__init__("options")
        self.GROUPS = (Group.INFRA, Group.CICD)
