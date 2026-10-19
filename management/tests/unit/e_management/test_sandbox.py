"""tests/unit/e_management/sandbox: a generated project stands on its own — real trees, real assembled CI, the generated contract test executed."""

import runpy
from typing import TYPE_CHECKING

import eserde
import pytest

from e_management.__main__ import main

if TYPE_CHECKING:
    from pathlib import Path


def _gen(tmp_path: Path, *argv: str) -> Path:
    dest = tmp_path / f"e-{argv[1]}"
    assert main(["gen", *argv, "--dest", str(dest)]) == 0
    return dest


@pytest.mark.parametrize(("template", "name"), [("api", "sandapi"), ("cli", "sandcli"), ("tui", "sandtui")])
def test_generated_tree_is_a_complete_project(tmp_path: Path, template: str, name: str) -> None:
    dest = _gen(tmp_path, template, name)
    assert (dest / "pyproject.toml").is_file()
    assert (dest / "src" / f"e_{name}" / "main.py").is_file() or (dest / "src" / f"e_{name}").is_dir()
    assert (dest / ".github" / "ci.vars.example").is_file(), "the gate manifest must travel with the project"
    assert (dest / ".github" / "INSTALL.md").is_file(), "the install instructions must travel with the project"


def test_assembled_workflows_are_valid_and_gates_are_inert(tmp_path: Path) -> None:
    dest = _gen(tmp_path, "api", "sandgates")
    for file in (dest / ".github" / "workflows").glob("*.yml"):
        eserde.load(file, format="yaml")
    manifest = (dest / ".github" / "ci.vars.example").read_text()
    lines = [line for line in manifest.splitlines() if "=" in line and not line.startswith("#")]
    assert lines, "the manifest must list a line per gate"
    assert all(line.split("=")[1].split()[0] == "false" for line in lines), manifest


def test_the_generated_contract_test_passes_against_the_generated_tree(tmp_path: Path) -> None:
    dest = _gen(tmp_path, "api", "sandcontract")
    module = runpy.run_path(str(dest / "tests" / "unit" / "test_ci_contract.py"))
    for name, fn in module.items():
        if name.startswith("test_"):
            fn()


def test_ci_off_prunes_both_the_job_and_the_gate(tmp_path: Path) -> None:
    dest = _gen(tmp_path, "api", "sandoff", "--ci-off", "docs")
    ci = (dest / ".github" / "workflows" / "ci.yml").read_text()
    assert "# feature: docs" not in ci
    assert "DOCS_DEPLOY" not in ci
    assert "DOCS_DEPLOY" not in (dest / ".github" / "ci.vars.example").read_text()
    assert "docs" not in (dest / ".github" / "ci.map.yml").read_text()


def test_ci_on_adds_selfmaintain_beyond_the_reference(tmp_path: Path) -> None:
    dest = _gen(tmp_path, "api", "sandon", "--ci-on", "selfmaintain")
    workflows = dest / ".github" / "workflows"
    assert {"sync.yml", "ai-fix.yml", "health.yml"} <= {file.name for file in workflows.iterdir()}
    assert "# feature: selfmaintain" in (workflows / "ci.yml").read_text()
    assert "src/e_sandon/.*" in (workflows / "ai-fix.yml").read_text()
    assert "APP_CLIENT_ID" in (dest / ".github" / "ci.map.yml").read_text()
    assert "APP_CLIENT_ID" not in (dest / ".github" / "ci.vars.example").read_text()


def test_turning_a_choice_off_folds_its_dependent_feature(tmp_path: Path) -> None:
    dest = _gen(tmp_path, "api", "sandimg", "--off", "docker")
    assert not (dest / "Dockerfile").exists()
    assert "# feature: image" not in (dest / ".github" / "workflows" / "release.yml").read_text()
    assert "PUBLISH_IMAGE" not in (dest / ".github" / "ci.vars.example").read_text()


def test_off_pypi_leaves_no_release_workflow_at_all(tmp_path: Path) -> None:
    dest = _gen(tmp_path, "api", "sandbare", "--ci-off", "pypi,image")
    assert not (dest / ".github" / "workflows" / "release.yml").exists()
    assert (dest / ".github" / "workflows" / "ci.yml").is_file()


def test_reference_features_shape_what_arrives(tmp_path: Path) -> None:
    dest = _gen(tmp_path, "cli", "sandloop")
    assert not (dest / ".github" / "workflows" / "sync.yml").exists(), "cli's reference does not ship the loop"
    assert "# feature: ci-basics" in (dest / ".github" / "workflows" / "ci.yml").read_text()
