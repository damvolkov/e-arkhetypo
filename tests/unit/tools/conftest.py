import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

import changelog

TOOL = Path(changelog.__file__)


@pytest.fixture
def tool() -> ModuleType:
    return changelog


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A git repo on branch feat/x with one initial commit."""
    for argv in (
        ["init", "-q", "-b", "feat/x"],
        ["config", "user.email", "t@t"],
        ["config", "user.name", "t"],
        ["commit", "-q", "--allow-empty", "-m", "init"],
    ):
        subprocess.run(["git", "-C", str(tmp_path), *argv], check=True)
    return tmp_path


@pytest.fixture
def run(repo: Path):
    """The tool as a subprocess in the repo: argv in, return code out."""

    def _run(*argv: str) -> int:
        return subprocess.run([sys.executable, str(TOOL), "--root", str(repo), *argv], check=False).returncode

    return _run
