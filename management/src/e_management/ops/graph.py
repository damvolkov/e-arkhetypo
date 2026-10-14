"""ops.graph: the dependency analysis of a system — Rust-parsed imports, discovered unit catalog, and the pure graph algebra over them.

Three stages, each a named total: ``imports_of`` reads one file's concrete syntax tree; ``catalog`` walks a project's
``src/`` into units; ``resolve`` turns unit edges into levels, dependents and lock state. The transitive machinery
lives in ``ops.deps`` and is shared with the stack parser; this module is what is specific to a *system*: the AST
import extraction and the unit catalog.
"""

from typing import TYPE_CHECKING

import libcst as cst

from e_management.models.graph import Unit
from e_management.ops.deps import closure, levels, reverse

if TYPE_CHECKING:
    from collections.abc import Collection, Iterator, Mapping
    from pathlib import Path

    from e_management.models.manifest import Common

PY_SUFFIX: str = ".py"
INIT_NAME: str = "__init__.py"
MIN_DOTS: int = 2
SKIP_NAMES: frozenset[str] = frozenset({"__pycache__", INIT_NAME})


##### PARSING #####
def _dotted(node: cst.BaseExpression | None) -> str | None:
    match node:
        case None:
            return None
        case cst.Name(value=single):
            return single
        case cst.Attribute(value=inner, attr=cst.Name(value=tail)):
            return None if (prefix := _dotted(inner)) is None else f"{prefix}.{tail}"
        case _:
            return None


def _unit(dotted: str, areas: frozenset[str]) -> str | None:
    """``adapters.base`` → ``adapters/base``; a head that is not a common area (the app itself) names no unit."""
    parts = dotted.split(".")
    return f"{parts[0]}/{parts[1]}" if len(parts) >= MIN_DOTS and parts[0] in areas else None


def _from_dots(node: cst.ImportFrom) -> tuple[str, ...]:
    base = _dotted(node.module)
    if not base:
        return ()
    match node.names:
        case None | cst.ImportStar():
            return (base,)
        case aliases:
            return (base, *(f"{base}.{name}" for alias in aliases if (name := _dotted(alias.name))))


def _import_dots(node: cst.Import) -> tuple[str, ...]:
    match node.names:
        case None | cst.ImportStar():
            return ()
        case aliases:
            return tuple(name for alias in aliases if (name := _dotted(alias.name)))


class _Refs(cst.CSTVisitor):
    """A libcst dispatch hook — collects the dotted names every import statement mentions."""

    def __init__(self) -> None:
        self.dots: list[str] = []

    def visit_ImportFrom(self, node: cst.ImportFrom) -> None:  # noqa: N802 — libcst dispatches by node class name
        self.dots.extend(_from_dots(node))

    def visit_Import(self, node: cst.Import) -> None:  # noqa: N802 — libcst dispatches by node class name
        self.dots.extend(_import_dots(node))


def imports_of(text: str, areas: frozenset[str]) -> frozenset[str]:
    """Every common unit a source file references, read from its concrete syntax tree."""
    visitor = _Refs()
    cst.parse_module(text).visit(visitor)
    return frozenset(unit for dot in visitor.dots if (unit := _unit(dot, areas)))


##### DISCOVERY #####
def _pyfiles(base: Path) -> Iterator[Path]:
    return (p for p in sorted(base.rglob("*.py")) if "__pycache__" not in p.parts)


def areas_of(src: Path, package: str) -> tuple[str, ...]:
    """The top-level ``src`` directories that are neither the app package nor empty of code."""
    return tuple(sorted(p.name for p in src.iterdir() if p.is_dir() and p.name != package and any(p.glob("*.py"))))


def _cells(src: Path, areas: tuple[str, ...]) -> Iterator[tuple[str, Path, bool]]:
    """Each candidate unit as (area, path, is_package): flat modules and one-level packages, nothing else."""
    return (
        (area, child, child.is_dir())
        for area in areas
        for child in sorted((src / area).iterdir())
        if child.name not in SKIP_NAMES
        and ((child.is_file() and child.suffix == PY_SUFFIX) or (child.is_dir() and (child / INIT_NAME).is_file()))
    )


def _key(area: str, child: Path, *, is_package: bool) -> str:
    return f"{area}/{child.name if is_package else child.stem}"


def _rel(system: Path, path: Path) -> str:
    return path.relative_to(system).as_posix()


def catalog(src: Path, areas: tuple[str, ...]) -> tuple[dict[str, tuple[str, ...]], dict[str, bool]]:
    """The unit catalog: the project-relative files each unit owns, and whether it is a package."""
    system = src.parent
    cells = list(_cells(src, areas))
    files = {
        _key(area, child, is_package=pkg): tuple(sorted(_rel(system, p) for p in ([child] if not pkg else _pyfiles(child))))
        for area, child, pkg in cells
    }
    packages = {_key(area, child, is_package=pkg): pkg for area, child, pkg in cells}
    return files, packages


def core_tests(common: Common, common_dir: Path, keys: Collection[str]) -> dict[str, tuple[str, ...]]:
    """The core tests each unit owns, spelled as the destination paths they materialize to in a generated project."""
    root = common_dir / "tests" / "unit" / common.package
    return {
        key: tuple(f"tests/unit/{key.partition('/')[0]}/{name}" for name in sorted(p.name for p in (root / key.partition('/')[0]).glob(f"test_{key.partition('/')[2]}*.py")))
        if (root / key.partition("/")[0]).is_dir()
        else ()
        for key in keys
    }


##### SYSTEM ALGEBRA #####
def forward(
    keys: Collection[str],
    files_of: Mapping[str, Collection[str]],
    imports_of_map: Mapping[str, Collection[str]],
    skip: frozenset[str],
) -> dict[str, frozenset[str]]:
    """Unit→unit imports: what a unit's files reference that is a live unit, never the unit itself."""
    valid = set(keys) - skip
    return {
        key: frozenset(unit for src in files_of[key] for unit in imports_of_map[src] if unit in valid) - {key}
        for key in valid
    }


def pinned(
    root_files: Collection[str],
    imports_map: Mapping[str, Collection[str]],
    deps: Mapping[str, frozenset[str]],
    detach: frozenset[str],
) -> frozenset[str]:
    """Units the service pins: imported by the app root, minus those a detach rule releases, closed forward."""
    direct = {unit for src in root_files for unit in imports_map[src] if unit in deps}
    return closure(direct - detach, deps)


def resolve(
    *,
    keys: Collection[str],
    files_of: Mapping[str, tuple[str, ...]],
    tests_of: Mapping[str, tuple[str, ...]],
    package_of: Mapping[str, bool],
    imports_map: Mapping[str, frozenset[str]],
    root_files: Collection[str],
    detach: frozenset[str],
    skip: frozenset[str],
) -> tuple[Unit, ...]:
    """The whole classification: every live unit with its edges, closures, level and lock state, sorted by key."""
    deps = forward(keys, files_of, imports_map, skip)
    back = reverse(deps)
    rank = levels(deps)
    locked = pinned(root_files, imports_map, deps, detach)
    return tuple(
        Unit(
            key=key,
            area=key.partition("/")[0],
            name=key.partition("/")[2],
            package=package_of[key],
            files=files_of[key],
            tests=tests_of.get(key, ()),
            deps=tuple(sorted(deps[key])),
            dependents=tuple(sorted(back[key])),
            closure=tuple(sorted(closure(deps[key], deps))),
            level=rank[key],
            locked=key in locked,
            detachable=key in detach,
        )
        for key in sorted(deps)
    )
