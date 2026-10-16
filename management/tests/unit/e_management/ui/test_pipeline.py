"""tests/unit/e_management/ui/pipeline: the generate worker — apply plus the template's verify steps, with the outside world faked."""

from typing import TYPE_CHECKING

from e_management.adapters.draft import DraftStore
from e_management.adapters.runner import CommandRunner
from e_management.adapters.scaffold import Scaffold
from e_management.core.session import Session
from e_management.ui.app import ManagementApp
from e_management.ui.screens import ReportScreen

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

    from e_management.core.plan import Plan
    from e_management.models.manifest import Manifest


def at_confirm(tmp_path: Path, repo: Path, spec: Manifest, dest: Path, *, tests: bool = True) -> ManagementApp:
    """A wizard resumed at the end of its walk, the destination decided and the unit tests answered."""
    DraftStore(tmp_path / "draft.json").save(
        Session(
            template="api", name="myapp", dest=str(dest), verify_tests=tests, at="confirm", trail=("system", "name")
        )
    )
    return ManagementApp(spec, repo, tmp_path / "draft.json")


def fake_scaffold(monkeypatch: pytest.MonkeyPatch, ok: bool = True) -> None:
    def apply(_self, plan: Plan, target: Path) -> Path:
        if not ok:
            msg = "nope"
            raise FileExistsError(msg)
        target.mkdir(parents=True, exist_ok=True)
        return target

    monkeypatch.setattr(Scaffold, "apply", apply)


def fake_runner(monkeypatch: pytest.MonkeyPatch, code: int = 0) -> list[list[str]]:
    calls: list[list[str]] = []

    async def run(_self, argv, cwd, emit):
        calls.append(list(argv))
        await emit(f"ran {argv[0]}")
        return code

    monkeypatch.setattr(CommandRunner, "run", run)
    return calls


async def test_pipeline_runs_apply_then_verify_and_reports_ready(
    tmp_path: Path, repo: Path, spec: Manifest, monkeypatch
) -> None:
    fake_scaffold(monkeypatch)
    calls = fake_runner(monkeypatch)
    app = at_confirm(tmp_path, repo, spec, tmp_path / "e-myapp")
    async with app.run_test(size=(120, 40)) as pilot:
        app._generate()
        await pilot.pause(0.4)
        assert isinstance(app.screen, ReportScreen)
        assert app.screen.ok is True
    assert [argv[0] for argv in calls] == ["git", "uv", "make"]


async def test_pipeline_skips_test_steps_when_declined(tmp_path: Path, repo: Path, spec: Manifest, monkeypatch) -> None:
    fake_scaffold(monkeypatch)
    calls = fake_runner(monkeypatch)
    app = at_confirm(tmp_path, repo, spec, tmp_path / "e-myapp", tests=False)
    async with app.run_test(size=(120, 40)) as pilot:
        app._generate()
        await pilot.pause(0.4)
    assert [argv[0] for argv in calls] == ["git"]


async def test_pipeline_stops_at_first_failing_step(tmp_path: Path, repo: Path, spec: Manifest, monkeypatch) -> None:
    fake_scaffold(monkeypatch)
    calls = fake_runner(monkeypatch, code=7)
    app = at_confirm(tmp_path, repo, spec, tmp_path / "e-myapp")
    async with app.run_test(size=(120, 40)) as pilot:
        app._generate()
        await pilot.pause(0.4)
        assert isinstance(app.screen, ReportScreen)
        assert app.screen.ok is False
    assert len(calls) == 1


async def test_pipeline_reports_apply_failure(tmp_path: Path, repo: Path, spec: Manifest, monkeypatch) -> None:
    fake_scaffold(monkeypatch, ok=False)
    calls = fake_runner(monkeypatch)
    app = at_confirm(tmp_path, repo, spec, tmp_path / "e-myapp")
    async with app.run_test(size=(120, 40)) as pilot:
        app._generate()
        await pilot.pause(0.4)
        assert isinstance(app.screen, ReportScreen)
        assert app.screen.ok is False
    assert calls == []


async def test_generate_refuses_a_lived_destination(tmp_path: Path, repo: Path, spec: Manifest, monkeypatch) -> None:
    dest = tmp_path / "e-myapp"
    dest.mkdir()
    (dest / "something").write_text("keep")
    fake_scaffold(monkeypatch)
    calls = fake_runner(monkeypatch)
    app = at_confirm(tmp_path, repo, spec, dest)
    async with app.run_test(size=(120, 40)) as pilot:
        app._generate()
        await pilot.pause()
        assert not isinstance(app.screen, ReportScreen)
    assert calls == [], "an occupied destination must stop the engine before it runs a step"
