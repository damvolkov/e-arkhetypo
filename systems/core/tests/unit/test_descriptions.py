"""tests/unit/test_descriptions: every module of e_core carries a short, prefixed top description — the contract management's surfaces read."""

import ast
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[2] / "src" / "e_core"
LIMIT = 120


def _modules() -> list[tuple[str, Path]]:
    return [
        (str(path.relative_to(PACKAGE).with_suffix("")).removesuffix("__init__").removesuffix("/"), path)
        for path in sorted(PACKAGE.rglob("*.py"))
        if "__pycache__" not in path.parts
    ]


@pytest.mark.parametrize(("relpath", "path"), _modules(), ids=[name for name, _ in _modules()])
def test_descriptions_module_prefixed(relpath: str, path: Path) -> None:
    doc = ast.get_docstring(ast.parse(path.read_text("utf-8")))
    assert doc, f"{relpath}: no docstring"
    first = doc.splitlines()[0].strip()
    assert first.startswith(f"{relpath}: "), f"{relpath}: top line must start with its path"
    assert first.endswith("."), f"{relpath}: top line must be one finished sentence"
    assert len(first) <= LIMIT, f"{relpath}: top description must stay short ({len(first)})"
