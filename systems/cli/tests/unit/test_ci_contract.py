"""Anti-drift contract for the optional CI/CD gates. Generated from infra/ — do not edit by hand.

Claims live in one machine-readable manifest (``.github/ci.vars.example``) and every claim is executed
against reality — the assembled workflows — in both directions. A gate used but undocumented, documented
but unused, or enabled by default fails the test. The declared features (``.github/ci.map.yml``) are the
third witness: every gate they name must be in the manifest.
"""

from __future__ import annotations

import functools
import re
from pathlib import Path
from typing import Final

import eserde

REPO: Final = Path(__file__).resolve().parents[2]
WORKFLOWS: Final = REPO / ".github" / "workflows"
MANIFEST: Final = REPO / ".github" / "ci.vars.example"
MAPFILE: Final = REPO / ".github" / "ci.map.yml"

VAR_RE: Final = re.compile(r"\bvars\.([A-Z][A-Z0-9_]*)\b")
ENTRY_RE: Final = re.compile(r"^([A-Z][A-Z0-9_]*)=(\S+)\s*(?:#\s*(\S.*))?$")


@functools.cache
def config_vars() -> frozenset[str]:
    """The config vars the declared features read (`vars:` in the map) — settings, not gates."""
    return frozenset(eserde.load(MAPFILE, format="yaml").get("vars", ()) if MAPFILE.is_file() else ())


@functools.cache
def gates_used() -> set[str]:
    """Gate names the workflows reference, the features' config vars aside; cached, the files do not move."""
    used = {m.group(1) for file in WORKFLOWS.glob("*.yml") for m in VAR_RE.finditer(file.read_text("utf-8"))}
    return used - config_vars()


@functools.cache
def gates_declared() -> dict[str, tuple[str, str]]:
    """Manifest entries name -> (default, doc); the walrus binds each match once, the cache answers every test."""
    return {
        m.group(1): (m.group(2), m.group(3) or "")
        for line in MANIFEST.read_text("utf-8").splitlines()
        if (m := ENTRY_RE.match(line.strip()))
    }


def test_every_gate_used_by_workflows_is_documented() -> None:
    missing = gates_used() - gates_declared().keys()
    assert not missing, f"undocumented CI gates in workflows: {sorted(missing)} (add them to {MANIFEST.name})"


def test_every_documented_gate_is_used() -> None:
    unused = gates_declared().keys() - gates_used()
    assert not unused, f"dead gate entries in {MANIFEST.name}: {sorted(unused)}"


def test_every_gate_ships_inert() -> None:
    live = {name: default for name, (default, _) in gates_declared().items() if default != "false"}
    assert not live, f"gates must default to inert (false) in {MANIFEST.name}: {live}"


def test_every_gate_documents_its_effect() -> None:
    undocumented = [name for name, (_, doc) in gates_declared().items() if not doc]
    assert not undocumented, f"gates without an inline description: {undocumented}"


def test_workflows_are_valid_yaml() -> None:
    for file in WORKFLOWS.glob("*.yml"):
        eserde.load(file, format=eserde.Format.YAML)  # a malformed assembly must die here, not on a runner


def test_declared_features_keep_their_gates_true_to_name() -> None:
    """A feature the repo enabled must document its gate and use it — or declare none."""
    if not MAPFILE.is_file():
        return
    declared = set(eserde.load(MAPFILE, format=eserde.Format.YAML).get("features", ()))
    assert declared, f"{MAPFILE.name}: declared features list is empty"
    installed = set(re.findall(r"^  # feature: (\S+)", _all_workflows(), flags=re.MULTILINE))
    assert installed <= declared, f"jobs from features never declared: {sorted(installed - declared)}"


def _all_workflows() -> str:
    return "".join(file.read_text("utf-8") for file in sorted(WORKFLOWS.glob("*.yml")))
