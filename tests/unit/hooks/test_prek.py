import os
import shlex
import subprocess
import tomllib
from pathlib import Path

import pytest

PREK = Path(__file__).resolve().parents[3] / "projects" / "python" / "common" / "prek.toml"


def _entry() -> list[str]:
    hooks = [h for repo in tomllib.loads(PREK.read_text())["repos"] for h in repo["hooks"]]
    return shlex.split(next(h for h in hooks if h["id"] == "changelog")["entry"])


@pytest.fixture
def staged(tmp_path: Path) -> Path:
    for argv in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", "-C", str(tmp_path), *argv], check=True)
    (tmp_path / "CHANGELOG.md").write_text("a\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-q", "-m", "i"], check=True)
    (tmp_path / "CHANGELOG.md").write_text("b\n")
    return tmp_path


@pytest.mark.parametrize(
    ("stage", "fold", "code"),
    [(True, None, 1), (True, "1", 0), (False, None, 0)],
    ids=["staged-blocked", "staged-fold", "unstaged-clean"],
)
async def test_changelog_hook(staged: Path, stage: bool, fold: str | None, code: int) -> None:
    stage and subprocess.run(["git", "-C", str(staged), "add", "CHANGELOG.md"], check=True)
    env = {k: v for k, v in os.environ.items() if k != "CHANGELOG_FOLD"} | ({"CHANGELOG_FOLD": fold} if fold else {})
    assert subprocess.run(_entry(), cwd=staged, env=env, check=False, capture_output=True).returncode == code


def _frozen_entry() -> list[str]:
    hooks = [h for repo in tomllib.loads(PREK.read_text())["repos"] for h in repo["hooks"]]
    return shlex.split(next(h for h in hooks if h["id"] == "frozen-templates")["entry"])


@pytest.mark.parametrize(
    ("path", "thaw", "code"),
    [
        ("projects/python/api/x.py", None, 1),
        ("projects/python/common/x.py", None, 0),
        ("projects/python/api/x.py", "1", 0),
        ("stack/x.yml", None, 0),
    ],
    ids=["template-blocked", "common-allowed", "template-thawed", "outside-projects"],
)
async def test_frozen_templates_hook(tmp_path: Path, path: str, thaw: str | None, code: int) -> None:
    _ = [
        subprocess.run(["git", "-C", str(tmp_path), *argv], check=True)
        for argv in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"])
    ]
    (tmp_path / "projects/python/common").mkdir(parents=True)
    (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / path).write_text("x\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", path], check=True)
    env = {k: v for k, v in os.environ.items() if k != "TEMPLATES_THAW"} | ({"TEMPLATES_THAW": thaw} if thaw else {})
    run = subprocess.run(
        _frozen_entry(), cwd=tmp_path / "projects/python/common", env=env, check=False, capture_output=True
    )
    assert run.returncode == code


async def test_frozen_templates_hook_is_inert_in_a_generated_project(tmp_path: Path) -> None:
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    (tmp_path / "projects/api").mkdir(parents=True)
    (tmp_path / "projects/api/x.py").write_text("x\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    assert subprocess.run(_frozen_entry(), cwd=tmp_path, check=False, capture_output=True).returncode == 0
