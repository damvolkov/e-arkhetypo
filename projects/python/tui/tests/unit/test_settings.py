"""tests/unit/settings: the template's own tree under the settings law — `infra.settings` read by the composition root
alone, and nothing but enums and value types taken from `infra.config` below it.

Common's gate holds the clusters (uppercase, one owner per field, the env snapshot) over common; this one holds the
reads over everything the template adds on top: its doors, its lifespans, its services."""

import ast
import re
from pathlib import Path
from typing import Final

from infra import settings as composer

### `src`: the template's package and the materialized sections beside it.
SOURCE: Final[Path] = Path(composer.__file__).resolve().parents[1]
CONFIG: Final[Path] = SOURCE / "infra" / "config"
### the composition root: entrypoints and the app they build, lifespans, request deps, the cli's runtime.
ROOT: Final[re.Pattern[str]] = re.compile(r"(^|/)(main|__main__|app|deps|cli|lifespan)\.py$|(^|/)(lifespan|runtime)/")


def imports(path: Path) -> list[tuple[str, str]]:
    """Every `from <module> import <name>` of a module."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        (node.module or "", alias.name)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    ]


def below() -> list[Path]:
    """The modules below the composition root: every source module but the settings, the config and the root."""
    return [
        path
        for path in SOURCE.rglob("*.py")
        if CONFIG not in path.parents
        and path.name != "settings.py"
        and not ROOT.search(path.relative_to(SOURCE).as_posix())
    ]


def test_settings_is_read_by_the_composition_root_alone() -> None:
    readers = {
        path.relative_to(SOURCE).as_posix()
        for path in below()
        for module, _ in imports(path)
        if module.endswith("infra.settings")
    }
    assert sorted(readers) == []


def test_below_the_root_config_gives_only_types() -> None:
    clusters = {
        f"{path.relative_to(SOURCE).as_posix()}:{name}"
        for path in below()
        for module, name in imports(path)
        if ".infra.config" in f".{module}" and name.endswith("Settings")
    }
    assert sorted(clusters) == []
