"""tests/unit/test_ops_contract: ops/ is a closed set of categories — the registry in docs/index.md is the law.

Every module under ``src/e_core/ops/`` names a category of the registry; the registry never grows past
20 categories; every public module-level function of ``ops/<category>.py`` carries its category as prefix.
The registry itself lives in the document that details the blueprint (``docs/index.md``), one line per
category: what it holds, what it never holds.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Final

import pytest

REPO: Final = Path(__file__).resolve().parents[2]
OPS: Final = REPO / "src" / "e_core" / "ops"
DOC: Final = REPO / "docs" / "index.md"
SECTION: Final = "## ops — the closed registry of categories"
LIMIT: Final = 20  # the house law: never more than twenty categories of agnostic tools
ROW_RE: Final = re.compile(r"^\|\s*`([a-z]+)`\s*\|")


def _section() -> list[str]:
    """The lines of the registry section, heading excluded, up to the next `## ` heading."""
    lines = DOC.read_text("utf-8").splitlines()
    assert SECTION in lines, f"{DOC}: no `{SECTION}` section — the registry is the contract, write it"
    start = lines.index(SECTION) + 1
    ends = [index for index, line in enumerate(lines[start:], start) if line.startswith("## ")]
    return lines[start : ends[0] if ends else len(lines)]


def _registry() -> list[str]:
    """The categories of the registry, in the order the table declares them."""
    return [m.group(1) for line in _section() if (m := ROW_RE.match(line))]


def _modules() -> list[str]:
    """Every ops module, named by its file."""
    return sorted(path.stem for path in OPS.glob("*.py"))


def _public_functions(module: str) -> list[str]:
    """The public module-level function names of one ops module."""
    tree = ast.parse((OPS / f"{module}.py").read_text("utf-8"))
    return [
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and not node.name.startswith("_")
    ]


def test_registry_exists_and_stays_within_the_limit() -> None:
    categories = _registry()
    assert categories, f"{DOC}: the registry section holds no category row"
    assert len(categories) <= LIMIT, f"the registry lists {len(categories)} categories; the limit is {LIMIT}"
    assert len(set(categories)) == len(categories), "a category is listed twice"


def test_every_ops_module_is_a_registered_category() -> None:
    outside = set(_modules()) - set(_registry())
    assert not outside, f"ops modules outside the registry: {sorted(outside)}"


@pytest.mark.parametrize("module", _modules())
def test_every_public_function_carries_its_category(module: str) -> None:
    offenders = [name for name in _public_functions(module) if not name.startswith(f"{module}_")]
    assert not offenders, f"ops/{module}.py: functions without the category prefix: {offenders}"
