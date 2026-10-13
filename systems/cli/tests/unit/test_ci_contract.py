"""Anti-drift contract for the optional CI/CD gates.

Mirrors the e-serde STANDARDS pattern: claims live in one machine-readable
manifest (``.github/ci.vars.example``) and every claim is executed against
reality — the workflows themselves — in both directions. A gate used but
undocumented, documented but unused, or enabled by default fails CI.
"""

from __future__ import annotations

import functools
import re
from pathlib import Path
from typing import Final

REPO: Final = Path(__file__).resolve().parents[2]
WORKFLOWS: Final = REPO / ".github" / "workflows"
MANIFEST: Final = REPO / ".github" / "ci.vars.example"

VAR_RE: Final = re.compile(r"\bvars\.([A-Z][A-Z0-9_]*)\b")
ENTRY_RE: Final = re.compile(r"^([A-Z][A-Z0-9_]*)=(\S+)\s*(?:#\s*(\S.*))?$")


@functools.cache
def gates_used() -> set[str]:
    """Gate names the workflows reference; cached because several tests ask, and the files do not move."""
    return {m.group(1) for file in WORKFLOWS.glob("*.yml") for m in VAR_RE.finditer(file.read_text("utf-8"))}


@functools.cache
def gates_declared() -> dict[str, tuple[str, str]]:
    """Manifest entries name → (default, doc); the walrus binds each match once, the cache answers every test."""
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


def test_release_jobs_gate_on_declared_vars() -> None:
    release = (WORKFLOWS / "release.yml").read_text("utf-8")
    declared = gates_declared().keys()
    assert re.search(rf"if: vars\.({'|'.join(declared)}) == 'true'", release), (
        "publish jobs must be gated by declared vars"
    )
