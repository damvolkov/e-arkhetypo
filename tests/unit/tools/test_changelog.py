import os
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

AREAS_TEXT = "# Changelog\n\n## [Unreleased]\n\n### stack\n\n- old stack\n\n### projects\n\n- old projects\n\n### infra\n\n- old infra\n\n## [1.0.0]\n\n- first\n"
PLAIN_TEXT = "# Changelog\n\n## [Unreleased]\n\n- old\n\n## [1.0.0]\n\n- first\n"


@pytest.mark.parametrize(
    ("branch", "expected"),
    [("feat/base-root", "feat-base-root"), ("main", "main"), ("a/b/c", "a-b-c")],
    ids=["slash", "plain", "nested"],
)
async def test_slug(tool: ModuleType, branch: str, expected: str) -> None:
    assert tool.slug(branch) == expected


async def test_fold_order_follows_the_given_sequence(tool: ModuleType) -> None:
    out = tool.fold(PLAIN_TEXT, ["- second\n", "- third\n"])
    assert out.index("- old") < out.index("- second") < out.index("- third") < out.index("## [1.0.0]")


async def test_fold_areas_land_in_their_section(tool: ModuleType) -> None:
    out = tool.fold(AREAS_TEXT, ["### infra\n\n- new infra\n\n### stack\n\n- new stack\n"])
    stack, projects, infra = (out.index(f"### {a}") for a in ("stack", "projects", "infra"))
    assert stack < out.index("- new stack") < projects < out.index("- old projects") < infra < out.index("- new infra")
    assert out.index("- new infra") < out.index("## [1.0.0]")


async def test_fold_missing_area_is_created(tool: ModuleType) -> None:
    text = "# Changelog\n\n## [Unreleased]\n\n### stack\n\n- old\n\n## [1.0.0]\n"
    out = tool.fold(text, ["### infra\n\n- new infra\n"])
    assert out.index("### infra") < out.index("- new infra") < out.index("## [1.0.0]")


async def test_fold_plain_file_drops_area_headings(tool: ModuleType) -> None:
    out = tool.fold(PLAIN_TEXT, ["### infra\n\n- new infra\n"])
    assert "### infra" not in out
    assert out.index("- old") < out.index("- new infra") < out.index("## [1.0.0]")


async def test_fold_wrapped_bullet_stays_whole(tool: ModuleType) -> None:
    out = tool.fold(PLAIN_TEXT, ["- long entry\n  continued here\n"])
    assert "- long entry\n  continued here\n" in out


async def test_fold_creates_unreleased_when_absent(tool: ModuleType) -> None:
    out = tool.fold("# Changelog\n\n## [1.0.0]\n\n- first\n", ["- new\n"])
    assert out.index("## [Unreleased]") < out.index("- new") < out.index("## [1.0.0]")


@pytest.mark.parametrize("text", [AREAS_TEXT, PLAIN_TEXT], ids=["areas", "plain"])
async def test_fold_idempotent(tool: ModuleType, text: str) -> None:
    once = tool.fold(text, ["- a\n", "### infra\n\n- b\n"])
    assert tool.fold(once, ["- a\n", "### infra\n\n- b\n"]) == once


async def test_fold_without_fragments_is_identity(tool: ModuleType) -> None:
    assert tool.fold(PLAIN_TEXT, []) == PLAIN_TEXT


async def test_record_adds_once_under_area(tool: ModuleType) -> None:
    once = tool.record("", "stack", "x")
    assert tool.record(once, "stack", "x") == once
    assert tool.record(once, "stack", "y").index("- x") < tool.record(once, "stack", "y").index("- y")
    assert "### stack" in once


async def test_record_cli_writes_the_branch_fragment_not_the_changelog(repo: Path, run) -> None:
    assert run("record", "--area", "infra", "--line", "did a thing") == 0
    assert "- did a thing" in (repo / "changelog.d" / "feat-x.md").read_text()
    assert not (repo / "CHANGELOG.md").exists()


async def test_fold_cli_folds_deletes_and_keeps_readme(repo: Path, run) -> None:
    (repo / "changelog.d").mkdir()
    (repo / "changelog.d" / "README.md").write_text("how this works\n")
    (repo / "CHANGELOG.md").write_text(PLAIN_TEXT)
    run("record", "--line", "from the branch")
    assert run("fold") == 0
    assert "- from the branch" in (repo / "CHANGELOG.md").read_text()
    assert sorted(p.name for p in (repo / "changelog.d").iterdir()) == ["README.md"]


async def test_fold_cli_orders_by_first_commit_date(repo: Path, run) -> None:
    (repo / "CHANGELOG.md").write_text(PLAIN_TEXT)
    (repo / "changelog.d").mkdir()
    for name, date in (("a-late.md", "2026-03-01T00:00:00"), ("z-early.md", "2026-01-01T00:00:00")):
        (repo / "changelog.d" / name).write_text(f"- {name}\n")
        env = {**os.environ, "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", name], check=True, env=env)
    run("fold")
    out = (repo / "CHANGELOG.md").read_text()
    assert out.index("z-early") < out.index("a-late")


async def test_fold_cli_twice_and_empty_is_noop(repo: Path, run) -> None:
    assert run("fold") == 0
    assert not (repo / "CHANGELOG.md").exists()
    (repo / "CHANGELOG.md").write_text(PLAIN_TEXT)
    run("record", "--line", "once")
    run("fold")
    after = (repo / "CHANGELOG.md").read_text()
    run("fold")
    assert (repo / "CHANGELOG.md").read_text() == after


async def test_fold_arealess_bullets_sit_above_the_areas(tool: ModuleType) -> None:
    out = tool.fold(AREAS_TEXT, ["- bare\n"])
    assert out.index("- bare") < out.index("### stack")
