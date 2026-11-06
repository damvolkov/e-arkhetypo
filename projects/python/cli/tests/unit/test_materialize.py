"""tests/unit/materialize: `scripts/materialize` keeps what a project owns in the shared homes.

`infra/config/` and `infra/settings.py` take common's clusters and default composer, but a file the project tracks
there is its own: a run writes around it, and the drift gate never flags it."""

import importlib.util
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from types import ModuleType

REPO: Final[Path] = Path(__file__).resolve().parents[2]
GIT: Final[str] = shutil.which("git") or "git"
OWN: Final[dict[str, str]] = {
    "infra/settings.py": '"""infra/settings: the project\'s own Settings."""\n',
    "infra/config/own.py": '"""infra/config/own: the project\'s own cluster."""\n',
}


def script() -> ModuleType:
    """`scripts/materialize.py` loaded as a module: scripts are not a package."""
    spec = importlib.util.spec_from_file_location("materialize", REPO / "scripts" / "materialize.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def owned(root: Path) -> None:
    """A project in `root` tracking its own settings and one cluster of its own."""
    _ = [
        (root / "src" / "e_cli" / rel).parent.mkdir(parents=True, exist_ok=True)
        or (root / "src" / "e_cli" / rel).write_text(body)
        for rel, body in OWN.items()
    ]
    subprocess.run([GIT, "init", "-q", str(root)], check=True)  # noqa: S603 — fixed argv, a tmp repo.
    subprocess.run([GIT, "-C", str(root), "add", "--", *(f"src/e_cli/{rel}" for rel in OWN)], check=True)  # noqa: S603 — fixed argv.


def test_materialize_keeps_the_projects_own_files(tmp_path: Path) -> None:
    owned(tmp_path)
    script().materialize(tmp_path)
    kept = {rel: (tmp_path / "src" / "e_cli" / rel).read_text() for rel in OWN}
    assert (kept, (tmp_path / "src" / "e_cli" / "infra" / "config" / "base.py").is_file()) == (OWN, True)


def test_check_ignores_the_projects_own_files(tmp_path: Path) -> None:
    owned(tmp_path)
    materialize = script()
    materialize.materialize(tmp_path)
    assert materialize.check(tmp_path) == 0
