"""ui.app: the wizard application — one Session holds every decision; only the generate step runs algorithms."""

import asyncio
from typing import TYPE_CHECKING, ClassVar

from msgspec import UNSET
from textual.app import App
from textual.binding import Binding
from textual.widgets import Footer

from e_management.adapters.draft import DraftStore
from e_management.adapters.runner import CommandRunner
from e_management.adapters.scaffold import Scaffold
from e_management.cli import commands
from e_management.core.session import Session, Step
from e_management.ui.screens import (
    CommonAreaScreen,
    ConfirmScreen,
    DependencyScreen,
    ModulesScreen,
    OptionsScreen,
    ProgressScreen,
    ReportScreen,
    SystemScreen,
)

if TYPE_CHECKING:
    from pathlib import Path

    from textual.app import ComposeResult
    from textual.screen import Screen

    from e_management.core.blueprint import Blueprint
    from e_management.core.plan import Plan
    from e_management.models.graph import Graph
    from e_management.models.manifest import Manifest

##### TYPES #####
SCREENS: dict[str, type] = {
    Step.SYSTEM: SystemScreen,
    "modules": ModulesScreen,
    "options": OptionsScreen,
    "confirm": ConfirmScreen,
}
APPLY = "apply"
TAIL = ("modules", "options", "confirm")


class ManagementApp(App[None]):
    """Owns the session, the draft, the live dependency graph and the pipeline: decisions accumulate, survive back, and generate on confirmation."""

    TITLE = "e-management"
    CSS: ClassVar[str] = """
    Screen { background: #04060b; }
    #trail { height: 1; margin: 1 2 0 2; }
    #stage {
        width: 100%;
        height: 1fr;
        border: round #1a2b55;
        border-title-color: #6f9bff;
        margin: 1 1 0 1;
        padding: 1 2 0 2;
        background: #060911;
    }
    .hint, .label { color: #56627a; margin-bottom: 1; }
    .label { margin: 1 0 0 0; }
    .error { color: #ff6b6b; height: auto; margin-bottom: 1; }
    Input { margin-bottom: 1; background: #02040a; border: tall #1a2233; }
    Input:focus { border: tall #3b6cf0; }

    /* tiles: off sits sunk into the panel (dark lip on top, light lip below); on stands out raised, in blue */
    .tiles { grid-size: 3; grid-gutter: 1 2; grid-rows: 4; height: auto; margin-bottom: 1; }
    .tile {
        width: 100%;
        height: 4;
        padding: 0 2;
        text-align: left;
        content-align: left middle;
        text-style: none;
        color: #5d6b85;
        background: #030509;
        border: none;
        border-top: tall #000000;
        border-bottom: tall #1c2638;
        tint: transparent;
    }
    .tile:hover { background: #0a1020; color: #9fb0cc; border-top: tall #000000; }
    .tile.-on {
        color: #f2f6ff;
        text-style: bold;
        background: #1f53e0;
        border-top: tall #6f9bff;
        border-bottom: tall #0c2a82;
    }
    .tile.-on:hover { background: #2a61f2; border-top: tall #8fb2ff; }
    .tile.-locked {
        color: #b4c4e6;
        background: #142552;
        border-top: tall #2d4d9a;
        border-bottom: tall #08132f;
    }
    .tile.-locked:hover { background: #172a5c; }
    .tile:focus { text-style: bold; }
    .tile.-active { border-top: tall #000000; border-bottom: tall #1c2638; }

    /* calls to action: the same raised blue as an ON tile */
    Button.-primary {
        color: #f2f6ff;
        text-style: bold;
        background: #1f53e0;
        border: none;
        border-top: tall #6f9bff;
        border-bottom: tall #0c2a82;
    }
    Button.-primary:hover { background: #2a61f2; border-top: tall #8fb2ff; }
    .actions { dock: bottom; height: auto; align-horizontal: right; padding-bottom: 1; }
    .actions Button { margin-left: 2; }
    .actions .tile { width: auto; height: 3; }
    #planbox { height: 1fr; border: round #1a2b55; background: #03050a; padding: 0 1; margin-bottom: 1; }
    Footer { background: #070b16; }
    """
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "step_back", "back"),
        Binding("g", "graph", "map", priority=True),
        Binding("ctrl+r", "reset", "reset"),
        Binding("ctrl+q", "quit", "quit"),
    ]

    def __init__(self, spec: Manifest, root: Path, draft_path: Path) -> None:
        super().__init__()
        self.spec = spec
        self.root = root
        self.draft = DraftStore(draft_path)
        self.session: Session = self.draft.load() or Session()
        self.plan_value: Plan | None = None
        self._maps: dict[str, Graph | None] = {}

    ##### PRIVATE #####

    async def _pipeline(self, plan: Plan) -> None:
        progress = ProgressScreen()
        await self.push_screen(progress)
        steps = [(APPLY, ()), *self.verify_steps()]
        ok = True
        for name, argv in steps:
            await progress.line(f"\n▶ {name}")
            ok = await self._run_step(plan, progress, tuple(argv))
            if not ok:
                break
        self.pop_screen()
        self.push_screen(ReportScreen(ok=ok, dest=self.session.target(), failures=progress.lines))

    async def _run_step(self, plan: Plan, progress: ProgressScreen, argv: tuple[str, ...]) -> bool:
        dest = self.session.target()
        if not argv:
            try:
                await asyncio.to_thread(Scaffold(self.root).apply, plan, dest)
            except OSError as exc:
                await progress.line(f"✗ apply: {exc}")
                return False
            return True
        return await CommandRunner().run(list(argv), dest, progress.line) == 0

    ############################################################

    ##### PUBLIC #####

    def compose(self) -> ComposeResult:
        yield Footer()

    def on_mount(self) -> None:
        self.push_screen(self.screen_for(self.session.stage()))

    def action_step_back(self) -> None:
        if len(self.screen_stack) > 1:
            self.pop_screen()

    def action_reset(self) -> None:
        """Abandon everything remembered and start the wizard from the first stage."""
        self.draft.drop()
        self.session = Session()
        self._maps.clear()
        self.switch_screen(SystemScreen())

    def action_graph(self) -> None:
        """Inspect the dependency map of the chosen template — a read-only overlay, never a wizard step."""
        self.push_screen(DependencyScreen())

    def save_draft(self) -> None:
        self.draft.save(self.session)

    def graph(self) -> Graph | None:
        """The live dependency graph of the chosen template — re-derived every app start, cached per template; None until one is chosen."""
        if self.session.template is UNSET:
            return None
        template = str(self.session.template)
        if template not in self._maps:
            self._maps[template] = commands.dependency_map(self.root, self.spec, template)
        return self._maps[template]

    def dependency_map(self) -> Graph:
        """The graph a decision screen requires — raises when the chosen template has nothing to graph."""
        found = self.graph()
        if found is None:
            msg = "the chosen template declares no common tree"
            raise ValueError(msg)
        return found

    def blueprint(self, name: str | None = None) -> Blueprint:
        return commands.blueprint(self.root, self.spec, str(self.session.template), name or str(self.session.name))

    def plan(self) -> Plan:
        """The preview of the whole session — pure until generate."""
        return self.blueprint().plan(frozenset(self.session.off), frozenset(self.session.drop))

    def begin_flow(self) -> None:
        """The step sequence of the chosen template: system, one panel per discovered area, then the fixed tail."""
        found = self.graph()
        areas = () if found is None else tuple(f"common-{area}" for area in found.area_names())
        self.session.steps = (Step.SYSTEM, *areas, *TAIL)

    def flow(self) -> tuple[str, ...]:
        """The step sequence known so far: the whole flow once a template is chosen, the fixed skeleton before."""
        return self.session.steps or (Step.SYSTEM, *TAIL)

    def screen_for(self, step: str) -> Screen:
        if step.startswith("common-"):
            return CommonAreaScreen(step.removeprefix("common-"))
        return SCREENS[step]()

    def advance(self, step: str) -> Screen:
        """The screen of the next step of the session's flow."""
        steps = self.flow()
        return self.screen_for(steps[steps.index(step) + 1])

    def suggested(self) -> Path:
        """Default destination: sibling of the templates repository, named after the brand."""
        return self.root.parent / f"e-{self.session.name}"

    def check_target(self, dest: Path) -> None:
        if dest.exists() and any(dest.iterdir()):
            msg = f"destination {dest} already exists and is not empty"
            raise FileExistsError(msg)

    def verify_steps(self) -> list[tuple[str, tuple[str, ...]]]:
        """The template's declared verification, obeying the user's choice on unit tests."""
        template = self.spec.templates[str(self.session.template)]
        return [(v.name, v.argv) for v in template.verify if self.session.verify_tests or not v.tests]

    def start_generate(self, plan: Plan) -> None:
        self.plan_value = plan
        self.run_worker(self._pipeline(plan), exclusive=True, group="generate")
