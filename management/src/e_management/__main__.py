"""python -m e_management: the tool's entry — no arguments opens the Textual wizard; the subcommands keep the headless surface."""

import argparse
import json
import sys
import tempfile
import webbrowser
from pathlib import Path
from typing import TYPE_CHECKING

import msgspec

from e_management.cli import commands
from e_management.ui.app import ManagementApp
from e_management.ui.view import render_map_html

if TYPE_CHECKING:
    from collections.abc import Sequence

    from e_management.models.manifest import Manifest

##### DEFAULTS #####
MANAGEMENT = Path(__file__).resolve().parents[2]
REPO = MANAGEMENT.parent


def _off(pieces: str) -> frozenset[str]:
    return frozenset(name for name in pieces.split(",") if name)


def _write_map(root: Path, spec: Manifest, names: Sequence[str]) -> Path:
    """Render the chosen systems' dependency maps to a self-contained HTML in the temp dir (never the repo)."""
    pairs = [(name, graph) for name in names if (graph := commands.dependency_map(root, spec, name)) is not None]
    out = Path(tempfile.gettempdir()) / "e-templates-depmap.html"
    out.write_text(render_map_html(pairs))
    return out


def _run(args: argparse.Namespace) -> int:  # noqa: PLR0912 — the verbs are the function: one branch per command, and it renders nothing.
    spec = commands.registry(args.manifest)
    match args.command:
        case "ui":
            ManagementApp(spec, args.root, MANAGEMENT / "data" / "draft.json").run()
        case "plan":
            actions = commands.plan(
                args.root,
                spec,
                args.template,
                args.name,
                off=_off(args.off),
                drop=_off(args.drop),
                ci_off=_off(args.ci_off),
            )
            print(json.dumps(msgspec.to_builtins(actions), indent=2))
        case "gen":
            dest = commands.gen(
                args.root,
                spec,
                args.template,
                args.name,
                args.dest.resolve(),
                off=_off(args.off),
                drop=_off(args.drop),
                ci_off=_off(args.ci_off),
            )
            print(f"created {dest}\nnext: cd {dest} && make install")
        case "drift":
            report = commands.drift(args.root, spec)
            for name, issues in report.items():
                print(f"{name}: {'in sync' if not issues else chr(10).join('  ' + i for i in issues)}")
            return int(any(report.values()))
        case "graph":
            for name, path in commands.graph(args.root, spec).items():
                print(f"{name}: wrote {path.relative_to(args.root)}")
        case "graph-check":
            report = commands.graph_drift(args.root, spec)
            for name, issues in report.items():
                print(f"{name}: {'in sync' if not issues else chr(10).join('  ' + i for i in issues)}")
            return int(any(report.values()))
        case "map":
            names = [args.template] if args.template else sorted(spec.templates)
            out = _write_map(args.root, spec, names)
            webbrowser.open(out.as_uri())
            print(f"{out}")
        case "stack":
            out = commands.stack_write(args.root)
            print(f"stack: wrote {out.relative_to(args.root)}")
        case "stack-check":
            issues = commands.stack_drift(args.root)
            print(f"stack: {'in sync' if not issues else chr(10).join('  ' + i for i in issues)}")
            return int(bool(issues))
        case "infra":
            for path in commands.infra_write(args.root, spec):
                print(f"infra: wrote {path.relative_to(args.root)}")
        case "infra-check":
            report = commands.infra_check(args.root, spec)
            for name, issues in report.items():
                print(f"{name}: {'in sync' if not issues else chr(10).join('  ' + i for i in issues)}")
            return int(any(report.values()))
        case "repo-infra":
            for path in commands.repo_write(args.root):
                print(f"repo-infra: wrote {path.relative_to(args.root)}")
        case "repo-infra-check":
            issues = commands.repo_drift(args.root)
            print(f"repo: {'in sync' if not issues else chr(10).join('  ' + i for i in issues)}")
            return int(bool(issues))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="e_management", description="e-templates boilerplate manager")
    parser.add_argument("--root", type=Path, default=REPO, help="repository root the registry paths hang from")
    parser.add_argument("--manifest", type=Path, default=MANAGEMENT / "data" / "templates.yml")
    subs = parser.add_subparsers(dest="command")
    subs.add_parser("ui")
    for name in ("plan", "gen"):
        sub = subs.add_parser(name)
        sub.add_argument("template")
        sub.add_argument("name")
        sub.add_argument("--off", default="", help="comma-separated choices to drop")
        sub.add_argument("--drop", default="", help="comma-separated common units to drop (area/unit)")
        sub.add_argument("--ci-off", default="", help="comma-separated CI features to drop")
        if name == "gen":
            sub.add_argument("--dest", type=Path, required=True)
    subs.add_parser("drift")
    subs.add_parser("graph")
    subs.add_parser("graph-check")
    subs.add_parser("stack")
    subs.add_parser("stack-check")
    subs.add_parser("infra")
    subs.add_parser("infra-check")
    subs.add_parser("repo-infra")
    subs.add_parser("repo-infra-check")
    mp = subs.add_parser("map")
    mp.add_argument("template", nargs="?", default="", help="a system name (default: every system)")
    args = parser.parse_args(list(argv) if argv is not None else None)
    args.command = args.command or "ui"
    return _run(args)


if __name__ == "__main__":
    sys.exit(main())
