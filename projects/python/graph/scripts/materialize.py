"""scripts/materialize: the hardened sed — copy `projects/python/common` sections into `src/e_graph/` with a structural rewrite.

libcst parses each source file as real 3.14 syntax (PEP 695 included, verified against the whole
`e_infra` tree) and rewrites *only* the import nodes `e_infra.<section> → e_graph.<section>` for the six sections;
every result is re-parsed with `ast.parse` and scanned for leftovers before it is written. `make common`
materializes into `src/e_graph/`; `make common-check` materializes into a throwaway tree under `/tmp` and diffs,
so both modes run the exact same generation path and the drift-check cannot lie about a second one.
"""

import argparse
import ast
import filecmp
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Final

import libcst as cst

if TYPE_CHECKING:
    from collections.abc import Sequence

API_ROOT: Path = Path(__file__).resolve().parents[1]
COMMON_SRC: Path = API_ROOT.parent / "common" / "src" / "e_infra"
PACKAGE: Final[str] = "e_graph"
SECTIONS: tuple[str, ...] = ("engines", "infra", "ops", "ports", "processors", "providers")
### the TUI header belongs to the boilerplate wizard, not to a running service: same topology as the old sed.
### the compose tool belongs to stack management (e-taxis materializes the whole ops area), not to a running service.
### the durable queue drivers (and the asyncpg driver PgQueuer rides) ride in only for a service that runs them: add
### asyncpg, pgqueuer and awa-pg, drop their exclusions and pick one in the composition root; the in-process
### supervisor (infra/background) and the dispatch engine over it ride in always. postgres rides in always — the db lifespan provisions every database the settings name.
### the embedding server, the in-process cache and the page extractor ride in only for a service that uses them: add
### tokenizers, theine or rtrafilatura and drop the exclusion.
EXCLUDES: frozenset[str] = frozenset(
    {
        "ops/tui.py",
        "ops/snap.py",
        "ops/compose.py",
        "providers/drivers/database/asyncpg.py",
        "providers/drivers/queue/awa.py",
        "providers/drivers/queue/pgqueuer.py",
        "providers/drivers/embed/tei.py",
        "providers/drivers/rerank/tei.py",
        "providers/adapters/cache/theine.py",
        "providers/adapters/extract/rtrafilatura.py",
        ##### auth and the MCP door: a service that runs a door (api) takes them #####
        "infra/auth/guard.py",
        "infra/auth/middleware.py",
        "infra/auth/models.py",
        "infra/auth/policy.py",
        "infra/auth/resolver.py",
        "infra/mcp/bridge.py",
        "infra/mcp/guard.py",
        "infra/mcp/models.py",
        "infra/mcp/mount.py",
        "infra/mcp/registry.py",
        "infra/mcp/server.py",
        "ports/auth.py",
        "providers/drivers/auth/postgres.py",
        "engines/auth.py",
    }
)


### the shared homes, under `src/e_graph`: common lands its clusters and a default `infra/settings.py` there, but a file the
### project tracks is its own — never written, pruned or flagged as drift; its `infra/settings.py` wins over common's
### default (e-nous `proj-py-layout/references/settings.md`). Every other path of a section is common's alone.
SHARED: Final[frozenset[str]] = frozenset({"infra/config", "infra/settings.py"})


##### REWRITE #####
def _parts(name: cst.BaseExpression) -> list[str] | None:
    """A dotted name as its segments; None when the node is not a plain dotted expression."""
    match name:
        case cst.Name(value=only):
            return [only]
        case cst.Attribute(value=inner, attr=cst.Name(value=tail)):
            return None if (prefix := _parts(inner)) is None else [*prefix, tail]
        case _:
            return None


def _dotted(parts: Sequence[str]) -> cst.BaseExpression:
    """The left-nested libcst attribute chain spelling `parts`."""
    match parts:
        case []:
            msg = "empty dotted name"
            raise ValueError(msg)
        case [only]:
            return cst.Name(only)
        case [*init, last]:
            return cst.Attribute(value=_dotted(init), attr=cst.Name(last))


def _reroot_e_infra(name: cst.BaseExpression) -> cst.BaseExpression:
    """`e_infra.infra.x` → `e_graph.infra.x`; anything outside a materialized section is returned untouched."""
    parts = _parts(name)
    hit = parts is not None and parts[0] == "e_infra" and len(parts) > 1 and parts[1] in SECTIONS
    return _dotted([PACKAGE, *parts[1:]]) if hit else name


def _reroot_alias(alias: object) -> object:
    """One `import a.b [as c]` alias, stripped whatever its wrapper shape; anything else passes through."""
    match alias:
        case cst.ImportAlias(name=name):
            return alias.with_changes(name=_reroot_e_infra(name))
        case cst.Element(node=cst.ImportAlias() as inner):
            return alias.with_changes(node=_reroot_alias(inner))
        case _:
            return alias


class _RerootEInfra(cst.CSTTransformer):
    """Import statements only: docstrings and comments keep naming the source of truth verbatim."""

    def leave_Import(  # noqa: N802 — libcst dispatches visitor methods by node class name
        self, _original_node: cst.Import, updated_node: cst.Import
    ) -> cst.Import:
        match updated_node.names:
            case cst.ImportStar():
                return updated_node
            case aliases:
                return updated_node.with_changes(names=[_reroot_alias(alias) for alias in aliases])

    def leave_ImportFrom(  # noqa: N802 — libcst dispatches by node class name
        self, _original_node: cst.ImportFrom, updated_node: cst.ImportFrom
    ) -> cst.ImportFrom:
        match updated_node.module:
            case None:
                return updated_node
            case module:
                return updated_node.with_changes(module=_reroot_e_infra(module))


##### VALIDATION #####
def _is_e_infra_import(node: ast.AST) -> bool:
    match node:
        case ast.ImportFrom(module=module) | ast.Import(names=[ast.alias(name=module), *_]):
            return bool(module) and module.split(".")[0] == "e_infra"
        case _:
            return False


def rewrite_source(text: str, path: str) -> str:
    """One file rewritten structurally, then hard-validated: parseable by `ast`, free of `e_infra` imports."""
    out = cst.parse_module(text).visit(_RerootEInfra()).code
    match [node for node in ast.walk(ast.parse(out, filename=path)) if _is_e_infra_import(node)]:
        case []:
            return out
        case leftovers:
            msg = f"{path}: unresolved e_infra imports survive the rewrite: {[n.lineno for n in leftovers]}"
            raise SystemExit(msg)


##### MATERIALIZATION #####
def _sources(section: str) -> list[Path]:
    """Every .py of one section, in stable order, minus the excluded files."""
    return [
        path
        for path in sorted((COMMON_SRC / section).rglob("*.py"))
        if "__pycache__" not in path.parts and str(path.relative_to(COMMON_SRC)) not in EXCLUDES
    ]


def _shared(rel: Path) -> bool:
    """A path under `src` inside a shared home: the project may own files there."""
    return any(rel.as_posix() == home or rel.as_posix().startswith(f"{home}/") for home in SHARED)


def _project(dest_root: Path) -> frozenset[Path]:
    """What the project owns inside the shared homes: what git tracks there. Common never writes over it."""
    found = subprocess.run(
        ["git", "-C", str(dest_root / "src" / PACKAGE), "ls-files", "--", *SHARED],
        capture_output=True,
        text=True,
        check=False,
    )
    return frozenset(rel for line in found.stdout.splitlines() if _shared(rel := Path(line)))


def materialize(dest_root: Path) -> None:
    """Write the rewritten sections under `dest_root/src/<package>`, replacing any previous copy — except what the project owns
    in a shared home, kept byte for byte."""
    src = dest_root / "src" / PACKAGE
    owned = {rel: (src / rel).read_bytes() for rel in _project(dest_root) if (src / rel).is_file()}
    for section in SECTIONS:
        shutil.rmtree(src / section, ignore_errors=True)
    for section in SECTIONS:
        for path in _sources(section):
            rel = path.relative_to(COMMON_SRC)
            target = src / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(rewrite_source(path.read_text(), str(rel)))
    for rel, body in owned.items():
        (src / rel).parent.mkdir(parents=True, exist_ok=True)
        (src / rel).write_bytes(body)


def _materialized(dest_root: Path) -> set[Path]:
    """The .py files currently materialized under `dest_root/src/<package>`, relative to it."""
    return {
        path.relative_to(dest_root / "src" / PACKAGE)
        for section in SECTIONS
        for path in (dest_root / "src" / PACKAGE / section).rglob("*.py")
    }


def check(dest_root: Path) -> int:
    """Regenerate into a throwaway tree under /tmp and diff against `dest_root`: 0 in sync, 1 on drift."""
    tmp = Path(tempfile.mkdtemp(prefix="e-graph-materialize-"))
    try:
        materialize(tmp)
        owned = _project(dest_root)
        expected = {path.relative_to(COMMON_SRC) for section in SECTIONS for path in _sources(section)} - owned
        actual = _materialized(dest_root) - owned
        issues = [
            *(f"{rel}: missing" for rel in sorted(expected - actual)),
            *(f"{rel}: extra" for rel in sorted(actual - expected)),
            *(
                f"{rel}: stale"
                for rel in sorted(expected & actual)
                if not filecmp.cmp(tmp / "src" / PACKAGE / rel, dest_root / "src" / PACKAGE / rel, shallow=False)
            ),
        ]
        match issues:
            case []:
                print("✓ materialized sections in sync")
                return 0
            case _:
                print("✗ drift from projects/python/common (run make common):")
                print("\n".join(f"  {issue}" for issue in issues))
                return 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI: default regenerates `src/`; `--check` is the read-only drift gate."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="regenerate into a tmp tree under /tmp and diff, exit 1 on drift"
    )
    match parser.parse_args(argv).check:
        case True:
            return check(API_ROOT)
        case _:
            materialize(API_ROOT)
            print(
                f"✓ materialized {', '.join(f'{PACKAGE}/{section}/' for section in SECTIONS)} from projects/python/common"
            )
            return 0


if __name__ == "__main__":
    sys.exit(main())
