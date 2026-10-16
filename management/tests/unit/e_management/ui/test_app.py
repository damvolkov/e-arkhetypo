"""tests/unit/e_management/ui/app: the wizard walks like the tui template — pages answered through the walker, the draft remembering every step."""

from typing import TYPE_CHECKING, Any, cast

from textual.widgets import Button, Static

import e_management.ui.app as app_module
from e_management.adapters.draft import DraftStore
from e_management.adapters.infra import InfraStore
from e_management.core.errors import InfraError
from e_management.core.session import Session
from e_management.ui.app import ManagementApp
from e_management.ui.screens import GraphScreen, ReportScreen
from e_management.ui.wizard import selection

if TYPE_CHECKING:
    from pathlib import Path

    from e_management.models.manifest import Manifest


def at(app: ManagementApp) -> str:
    return app._walk.state.at


def obj(app: ManagementApp) -> Any:
    """The interactive object mounted under the cursor — a typed hole for the template's own dials."""
    return cast("Any", app._object)


def pages(app: ManagementApp) -> list[str]:
    return [page.id for page in app._walk.state.graph.pages]


def commit(app: ManagementApp) -> None:
    """Accept the mounted page as it stands."""
    app.action_page_accept()


def toggle(app: ManagementApp, *off: str) -> None:
    """Switch the named fields off, leave every other switch as shown."""
    for key, switch in obj(app)._switches.items():
        if not switch.disabled:
            switch.value = key not in off


def choose(app: ManagementApp, key: str) -> None:
    """Light one radio of a choice page."""
    for name, radio in obj(app)._buttons.items():
        radio.value = name == key


def write(app: ManagementApp, text: str) -> None:
    """Type a line into an input page."""
    obj(app)._input.value = text


def confirm(app: ManagementApp, yes: bool = True) -> None:
    """Take the fork the way the buttons would."""
    obj(app)._answer = yes


async def test_the_flow_orders_the_sections(tmp_path: Path, repo: Path, spec: Manifest) -> None:
    app = ManagementApp(spec, repo, tmp_path / "draft.json")
    async with app.run_test(size=(120, 40)):
        areas = cast("Any", app._dep_map("api")).area_names()
        assert pages(app) == [
            "system",
            "name",
            *[f"tools-{area}" for area in areas],
            "options",
            "ci",
            "dest",
            "confirm",
        ]


async def test_an_empty_input_page_never_advances(tmp_path: Path, repo: Path, spec: Manifest) -> None:
    app = ManagementApp(spec, repo, tmp_path / "draft.json")
    async with app.run_test(size=(120, 40)):
        commit(app)
        assert at(app) == "name"
        commit(app)
        assert at(app) == "name", "a blank name must not commit"


async def test_walk_to_the_end_shows_plan_generate_and_draft(tmp_path: Path, repo: Path, spec: Manifest) -> None:
    draft = tmp_path / "draft.json"
    app = ManagementApp(spec, repo, draft)
    async with app.run_test(size=(120, 40)) as pilot:
        commit(app)  # system: api is pre-selected
        write(app, "myapp")
        for _ in range(7):
            commit(app)
        assert at(app) == "dest", [at(app)]
        write(app, str(tmp_path / "somewhere"))
        commit(app)
        assert at(app) == "confirm"
        confirm(app)
        commit(app)
        await pilot.pause()
        ids = {button.id.split("-")[0] for button in app.screen.query(Button)}
        assert {"go", "tests"} <= ids
        assert draft.exists(), "finishing the walk must remember the session"


async def test_bad_names_surface_at_the_end_view_not_the_walk(tmp_path: Path, repo: Path, spec: Manifest) -> None:
    app = ManagementApp(spec, repo, tmp_path / "draft.json")
    async with app.run_test(size=(120, 40)) as pilot:
        commit(app)
        write(app, "Bad Name")
        for _ in range(7):
            commit(app)
        assert at(app) == "dest", "a slug the domain will refuse still walks the flow"
        write(app, str(tmp_path / "d"))
        commit(app)
        confirm(app)
        commit(app)
        await pilot.pause()
        assert not any(b.id and b.id.startswith("go") for b in app.screen.query(Button)), (
            "no generate over an invalid plan"
        )
        assert any("✗" in str(static.visual) for static in app.screen.query(Static))


async def test_the_draft_resume_restores_cursor_and_answers(tmp_path: Path, repo: Path, spec: Manifest) -> None:
    draft = tmp_path / "draft.json"
    first = ManagementApp(spec, repo, draft)
    async with first.run_test(size=(120, 40)):
        commit(first)
        write(first, "myapp")
        for _ in range(3):
            commit(first)
        left_at = at(first)
        assert left_at in {"tools-core", "tools-ops", "tools-processors", "options"}

    resumed = ManagementApp(spec, repo, draft)
    async with resumed.run_test(size=(120, 40)):
        assert at(resumed) == left_at
        assert selection(resumed._walk.state.data)[4] == "myapp"


async def test_re_picking_the_system_rebuilds_the_flow(tmp_path: Path, repo: Path, spec: Manifest) -> None:
    app = ManagementApp(spec, repo, tmp_path / "draft.json")
    async with app.run_test(size=(120, 40)):
        choose(app, "cli")
        commit(app)
        assert at(app) == "system", "a rebuilt flow starts at its own head"
        assert "options" not in pages(app), "cli declares no choices: the section must be gone"
        assert app._template == "cli"


async def test_the_ci_page_locks_the_baseline(tmp_path: Path, repo: Path, spec: Manifest) -> None:
    app = ManagementApp(spec, repo, tmp_path / "draft.json")
    async with app.run_test(size=(120, 40)):
        commit(app)
        write(app, "myapp")
        for _ in range(6):
            commit(app)
        assert at(app) == "ci"
        locked = {key for key, switch in obj(app)._switches.items() if switch.disabled}
        assert locked == {"ci-basics"}
        toggle(app, "pypi")
        commit(app)
        write(app, str(tmp_path / "d"))
        commit(app)
        assert at(app) == "confirm"
        assert selection(app._walk.state.data)[2] == frozenset({"pypi"})


async def test_generate_runs_the_pipeline_and_reports(tmp_path: Path, repo: Path, spec: Manifest, monkeypatch) -> None:
    dest = tmp_path / "e-myapp"

    calls: list[tuple] = []

    class FakeScaffold:
        def __init__(self, _root) -> None:
            pass

        def apply(self, plan, target):
            calls.append(("apply", target))
            target.mkdir(parents=True)

    class FakeRunner:
        async def run(self, argv, cwd, emit):
            calls.append(("run", tuple(argv)))
            await emit(f"$ {' '.join(argv)}")
            return 0

    monkeypatch.setattr(app_module, "Scaffold", FakeScaffold)
    monkeypatch.setattr(app_module, "CommandRunner", FakeRunner)

    app = ManagementApp(spec, repo, tmp_path / "draft.json")
    async with app.run_test(size=(120, 40)) as pilot:
        commit(app)
        write(app, "myapp")
        for _ in range(7):
            commit(app)
        write(app, str(dest))
        commit(app)
        confirm(app)
        commit(app)  # confirm yes → the end view with the generate button
        await pilot.pause()
        app._generate()
        await pilot.pause()
        assert isinstance(app.screen, ReportScreen), calls
        assert ("apply", dest) in calls
        assert ("run", ("git", "init", "-q")) in calls


async def to_end(app: ManagementApp) -> None:
    """Walk the default answers all the way to the end view."""
    commit(app)
    write(app, "myapp")
    for _ in range(7):
        commit(app)
    write(app, "e-nowhere")
    commit(app)
    confirm(app)
    commit(app)


async def test_a_missing_library_hides_the_ci_page(tmp_path: Path, repo: Path, spec: Manifest, monkeypatch) -> None:
    def boom(self: InfraStore) -> None:
        msg = "no library"
        raise InfraError(msg)

    monkeypatch.setattr(InfraStore, "load", boom)
    app = ManagementApp(spec, repo, tmp_path / "draft.json")
    async with app.run_test(size=(120, 40)):
        assert "ci" not in pages(app)


async def test_a_missing_reference_hides_the_ci_page(tmp_path: Path, repo: Path, spec: Manifest, monkeypatch) -> None:
    def boom(self: InfraStore, system: str) -> None:
        msg = "no reference"
        raise InfraError(msg)

    monkeypatch.setattr(InfraStore, "defaults", boom)
    app = ManagementApp(spec, repo, tmp_path / "draft.json")
    async with app.run_test(size=(120, 40)):
        assert "ci" not in pages(app)


async def test_a_draft_with_unknown_pages_resumes_at_the_head(tmp_path: Path, repo: Path, spec: Manifest) -> None:
    draft = tmp_path / "draft.json"
    DraftStore(draft).save(
        Session(
            template="api",
            at="ghost",
            trail=("gone",),
            answers={"ghost": ("x",), "system": ("api",), "name": ("myapp",)},
        )
    )
    app = ManagementApp(spec, repo, draft)
    async with app.run_test(size=(120, 40)):
        assert at(app) == "system", "a draft pointing at pages that no longer exist resumes at the head"
        commit(app)
        assert at(app) == "name"
        assert obj(app)._input.value == "myapp"


async def test_the_tests_button_flips_the_switch_and_persists(tmp_path: Path, repo: Path, spec: Manifest) -> None:
    draft = tmp_path / "draft.json"
    app = ManagementApp(spec, repo, draft)
    async with app.run_test(size=(120, 40)) as pilot:
        await to_end(app)
        await pilot.pause()
        button = next(b for b in app.screen.query(Button) if b.id is not None and b.id.startswith("tests"))
        app.on_button_pressed(Button.Pressed(button))
        await pilot.pause()
    resumed = DraftStore(draft).load()
    assert resumed is not None
    assert resumed.verify_tests is False


async def test_back_and_reset_keep_writing_the_draft(tmp_path: Path, repo: Path, spec: Manifest) -> None:
    draft = tmp_path / "draft.json"
    app = ManagementApp(spec, repo, draft)
    async with app.run_test(size=(120, 40)):
        commit(app)
        assert _draft_at(draft) == "name"
        app.action_page_back()
        assert _draft_at(draft) == "system"
        commit(app)
        write(app, "myapp")
        commit(app)
        assert _draft_at(draft) != "system"
        app.action_page_reset()
        assert _draft_at(draft) == "system"


def _draft_at(draft: Path) -> str:
    session = DraftStore(draft).load()
    assert session is not None
    return session.at


async def test_the_graph_overlay_opens_and_escapes(tmp_path: Path, repo: Path, spec: Manifest) -> None:
    app = ManagementApp(spec, repo, tmp_path / "draft.json")
    async with app.run_test(size=(120, 40)) as pilot:
        app.action_show_graph()
        await pilot.pause()
        assert isinstance(app.screen, GraphScreen)
        app.screen.key_escape(None)
        await pilot.pause()
        assert not isinstance(app.screen, GraphScreen)
