"""ui.app: the wizard application — a `WizardApp` over the house flow. One walk answers every decision; the draft survives restarts; only the generate step touches the filesystem.

The chrome is the tui template's (mast, steps band, content, keys strip) because management *is* a
wizard built from that template, not a reimplementation of it. Pages come from `ui.wizard`, answers
land in `FlowState.data`, the plan preview and the install checklist mount at the walk's end, and
`generate` runs the pipeline over the verified plan. Re-picking the system mid-walk rebuilds the
graph for the new template — the answers that carried over (name, destination) are kept by the draft."""

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from textual.binding import Binding
from textual.widgets import Button, Static

from e_management.adapters.draft import DraftStore
from e_management.adapters.infra import InfraStore
from e_management.adapters.runner import CommandRunner
from e_management.adapters.scaffold import Scaffold
from e_management.cli import commands
from e_management.core.errors import ManagementError
from e_management.core.session import Session
from e_management.ui.screens import GraphScreen, ProgressScreen, ReportScreen
from e_management.ui.view import render_graph, render_plan
from e_management.ui.wizard import CI_OFF, DEST, DROP, NAME, OFF, TEMPLATE, build_graph, selection
from e_tui.app import WizardApp
from e_tui.flow.state import seed
from e_tui.flow.walk import Walker
from e_tui.layout.spec import Axis, Border, Box, Kind, Mast, Measure, Point

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from typing import Any

    from textual.widget import Widget

    from e_management.core.infra import Library
    from e_management.core.plan import Plan
    from e_management.models.graph import Graph as DepGraph
    from e_management.models.manifest import Manifest

##### TYPES #####
APPLY = "apply"


class ManagementApp(WizardApp):
    """The wizard: one flow over the template system, its tools, its choices and its CI, remembered by a draft."""

    TITLE = "e-management"
    KEY_HINT = "arrows move · space switch · enter accept · backspace back · g map · ctrl+r reset · ctrl+q quit"
    BINDINGS: ClassVar[list[Binding]] = [*WizardApp.BINDINGS, Binding("g", "show_graph", "map", priority=True)]
    SPEC: ClassVar[Box] = Box(
        id="stage",
        kind=Kind.STATIC,
        border=Border.FINE,
        axis=Axis.COLUMN,
        padding=1,
        children=(
            Box(
                id="header",
                kind=Kind.STATIC,
                border=Border.FINE,
                padding=1,
                size=Measure(frac=0.22, min_cells=6),
                mast=Mast(main="E-MANAGEMENT", sub="e-templates wizard", max_height=0.3),
            ),
            Box(
                id="content",
                kind=Kind.DYNAMIC,
                border=Border.FINE,
                axis=Axis.OVERLAY,
                padding=1,
                size=Measure(weight=1.0, min_cells=4),
                children=(
                    Box(
                        id="steps",
                        kind=Kind.DYNAMIC,
                        border=Border.FINE,
                        size=Measure(frac=0.92),
                        cross=Measure(frac=0.0, min_cells=1, max_cells=1),
                        offset=Point(x=0.04, y=0.04),
                    ),
                ),
            ),
            Box(
                id="keys",
                kind=Kind.DYNAMIC,
                border=Border.NONE,
                padding=0,
                size=Measure(frac=0.0, min_cells=1, max_cells=1),
            ),
        ),
    )

    def __init__(self, manifest: Manifest, root: Path, draft_path: Path) -> None:
        self._manifest = manifest
        self._root = root
        self._store = DraftStore(draft_path)
        self._session = self._store.load() or Session()
        self._infra = InfraStore(root)
        self._library: Library | None = self._load_library()
        self._maps: dict[str, DepGraph | None] = {}
        self._end_seq = 0
        self._template = self._session.template or min(manifest.templates)
        super().__init__(self._graph_for(self._template), result=self._end_view)
        self._restore(self._session)

    ##### WIRING #####

    def _load_library(self) -> Library | None:
        """The CI library once per process; a missing library keeps the wizard usable (no CI page)."""
        try:
            return self._infra.load()
        except ManagementError:
            return None

    def _graph_for(self, template: str) -> Any:
        """The flow of one template: sections built from the manifest, the dependency graph and the CI reference."""
        reference = self._reference(template)
        return build_graph(
            self._manifest,
            template,
            library=self._library if reference else None,
            reference=reference,
            dep_graph=self._dep_map(template),
            session=self._session,
        )

    def _reference(self, template: str) -> tuple[str, ...]:
        """The feature names the system's CI reference ships; empty when the system declares none."""
        try:
            return tuple(self._infra.defaults(self._manifest.templates[template].source).features)
        except ManagementError:
            return ()

    def _dep_map(self, template: str) -> DepGraph | None:
        """The live dependency graph of one system, cached per app — the tools pages read it, the overlay shows it."""
        if template not in self._maps:
            self._maps[template] = commands.dependency_map(self._root, self._manifest, template)
        return self._maps[template]

    ##### DRAFT #####

    def _restore(self, session: Session) -> None:
        """Place the cursor, the trail and the answers where the draft left them — the walk continues, not restarts."""
        state = self._walk.state
        pages = {page.id for page in state.graph.pages}
        if session.at in pages:
            state.at = session.at
            state.trail = tuple(step for step in session.trail if step in pages)
        for page_id, values in session.answers.items():
            if page_id in pages:
                state.answers[page_id] = values
        for key, value in {
            TEMPLATE: session.template,
            NAME: session.name,
            DEST: session.dest,
            OFF: session.off,
            DROP: session.drop,
            CI_OFF: session.ci_off,
        }.items():
            if value:
                seed(state.data, key, value)

    def _remember(self) -> None:
        """Snapshot the walk into the session and persist it — the unit of the wizard's memory."""
        off, drop, ci_off, template, name, dest = selection(self._walk.state.data)
        self._session = Session(
            template=template or self._template,
            name=name,
            off=tuple(sorted(off)),
            drop=tuple(sorted(drop)),
            ci_off=tuple(sorted(ci_off)),
            dest=dest,
            at=self._walk.state.at,
            trail=self._walk.state.trail,
            answers={page.id: self._walk.state.values_for(page.id) for page in self._walk.state.graph.pages},
            verify_tests=self._session.verify_tests,
        )
        self._store.save(self._session)
        if template and template != self._template:
            self._rebuild(template)

    def _rebuild(self, template: str) -> None:
        """A re-picked system is another flow: rebuild its graph, keep its name and destination, re-render."""
        self._template = template
        self._walk = Walker(self._graph_for(template))
        for key, value in {NAME: self._session.name, DEST: self._session.dest}.items():
            if value:
                seed(self._walk.state.data, key, value)
        self._render()  ### the template's own re-render seam — the viewer is a dumb matcher by design.

    ##### PLAN #####

    def _plan_for(self, data: Mapping[str, object]) -> Plan:
        """The ordered actions of the current answers — pure until generate."""
        off, drop, ci_off, template, name, _dest = selection(data)
        return commands.blueprint(self._root, self._manifest, template or self._template, name).plan(off, drop, ci_off)

    def plan(self) -> Plan:
        """The preview of the whole walk — raises the domain's own errors on an illegal selection."""
        return self._plan_for(self._walk.state.data)

    def suggested(self) -> Path:
        """Default destination: sibling of the templates repository, named after the brand."""
        return self._root.parent / f"e-{self._session.name or 'project'}"

    def check_target(self, dest: Path) -> None:
        if dest.exists() and any(dest.iterdir()):
            msg = f"destination {dest} already exists and is not empty"
            raise FileExistsError(msg)

    def target(self) -> Path:
        return Path(self._session.dest) if self._session.dest else self.suggested()

    ##### END VIEW #####

    def _end_view(self, data: Mapping[str, object]) -> Iterable[Widget]:
        """The payoff page: the plan, the install checklist, the tests switch and the generate call."""
        try:
            plan = self._plan_for(data)
        except ManagementError as exc:
            return [Static(f"✗ {exc}", markup=False)]
        self._end_seq += 1
        return [
            Static(render_plan(plan), markup=False),
            Button(
                f"unit tests after export: {'on' if self._session.verify_tests else 'off'}", id=f"tests-{self._end_seq}"
            ),
            Button("generate  →", id=f"go-{self._end_seq}", variant="primary"),
        ]

    def on_button_pressed(self, event: Button.Pressed) -> None:
        match (event.button.id or "").split("-")[0]:
            case "tests":
                self._session.verify_tests = not self._session.verify_tests
                self._store.save(self._session)
                self._end()  ### redraw the end view with the flipped switch.
            case "go":
                self._generate()
            case _:
                return

    ##### PIPELINE #####

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
        self.push_screen(ReportScreen(ok=ok, dest=self.target(), failures=progress.lines))

    async def _run_step(self, plan: Plan, progress: ProgressScreen, argv: tuple[str, ...]) -> bool:
        dest = self.target()
        if not argv:
            try:
                await asyncio.to_thread(Scaffold(self._root).apply, plan, dest)
            except OSError as exc:
                await progress.line(f"✗ apply: {exc}")
                return False
            return True
        return await CommandRunner().run(list(argv), dest, progress.line) == 0

    def verify_steps(self) -> list[tuple[str, tuple[str, ...]]]:
        """The template's declared verification, obeying the user's choice on unit tests."""
        template = self._manifest.templates[self._template]
        return [(step.name, step.argv) for step in template.verify if self._session.verify_tests or not step.tests]

    def _generate(self) -> None:
        """The only path that writes: validate the target, take the plan, run the pipeline in its worker."""
        try:
            self.check_target(self.target())
            plan = self.plan()
        except (ManagementError, OSError, ValueError) as exc:
            self.fill("content", Static(f"✗ {exc}", markup=False))
            return
        self._remember()
        self.run_worker(self._pipeline(plan), exclusive=True, group="generate")

    ##### ACTIONS #####

    def action_page_accept(self) -> None:
        """Advance the walk, then let the memory decide: the draft, and a rebuild if the system changed."""
        super().action_page_accept()
        self._remember()

    def action_page_back(self) -> None:
        super().action_page_back()
        self._remember()

    def action_page_reset(self) -> None:
        super().action_page_reset()
        self._remember()

    def action_show_graph(self) -> None:
        """Inspect the dependency map of the current template — a read-only overlay, never a wizard step."""
        self.push_screen(GraphScreen(render_graph(self._dep_map(self._template))))
