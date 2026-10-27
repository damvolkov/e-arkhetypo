""".github/tools/repo_health.py: the three-area health of a wide repo — stack images, system dependencies, action pins.

One report, three sections, split exactly the way the repo is maintained: ``stack`` reads the version
ledger (vanished images, refs the ledger never covered, stale resolution), ``projects`` runs the package
probe of ``.github/tools/health.py`` over every system's dependencies and checks the template registry against
disk, ``infra`` compares every action digest pinned in the CI fragments with its upstream release.
Stdlib only; exit 0 means every area clean, exit 3 means findings — the contract the workflow reads."""

import argparse
import concurrent.futures
import json
import re
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

import health
import stack_resolve

FINDINGS_EXIT = 3
LEDGER_STALE_DAYS = 45
CONCURRENCY = 8
TIMEOUT = 30
USER_AGENT = "e-stack-repo-health"
RESOLVED_RE = re.compile(r'^resolved: "(\d{4}-\d{2}-\d{2})"', re.MULTILINE)
BLOCK_RE = re.compile(r'- ref: "?([^\s"]+)"?\n((?:  \w+: .*\n?)+)')
FIELD_RE = re.compile(r'  (\w+): (.*)')
USES_RE = re.compile(r"uses:\s*([\w./-]+)@([0-9a-f]{40})\s*#\s*(\S+)")
SOURCE_RE = re.compile(r"^\s*source:\s*(projects/python/\w+)\s*$", re.MULTILINE)

Row = tuple[str, str, str, str]


def _get(url: str, token: str) -> Any:
    """A JSON GET; a 404 or any failure answers None — a missing upstream is a finding, not a crash."""
    headers = {"User-Agent": USER_AGENT}
    if token and url.startswith("https://api.github.com/"):
        headers["Authorization"] = f"Bearer {token}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=TIMEOUT) as response:
            return json.load(response)
    except Exception:  # noqa: BLE001
        return None


def _days(date: str) -> float:
    """Days between a YYYY-MM-DD date and now."""
    return (time.time() - time.mktime(time.strptime(date, "%Y-%m-%d"))) / 86400


##### STACK #####


def stack_rows(root: Path) -> list[Row]:
    """Findings over the version ledger and the compose files it must cover."""
    ledger = root / "stack" / "stack.versions.yml"
    if not ledger.is_file():
        return [("ledger", "file", "never-resolved", "run sync-stack to create stack/stack.versions.yml")]
    text = ledger.read_text()
    entries = {ref: {key: value.strip('"') for key, value in FIELD_RE.findall(body)} for ref, body in BLOCK_RE.findall(text)}
    rows = [
        (ref, f'registry: {entry["registry"]}', "vanished", "the image or tag no longer answers — mark the service deprecated or park it")
        for ref, entry in entries.items()
        if entry.get("vanished") == "true" and entry.get("parked") != "true"
    ]
    if (stamp := RESOLVED_RE.search(text)) and _days(stamp.group(1)) > LEDGER_STALE_DAYS:
        rows.append(("ledger", "file", "stale", f"last resolved {int(_days(stamp.group(1)))} days ago"))
    rows += [
        (ref, "compose", "uncovered", f"`{service}` is in the stack but not in the ledger — re-run sync-stack")
        for service, _, ref, _, _ in stack_resolve.refs(root / "stack")
        if ref not in entries
    ]
    return rows


##### PROJECTS #####


def projects_rows(root: Path, token: str) -> list[Row]:
    """Findings per system: every dependency probed with .github/tools/health, plus registry sources missing from disk."""
    projects = sorted(path.parent for path in root.glob("projects/python/*/pyproject.toml"))
    pairs = [(project.name, dep) for project in projects for dep in health.requirements(project)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        checked = dict(pool.map(lambda pair: (pair, health.check(pair[1], token)), pairs))
    rows = [
        (f"{project}: {dep}", registry, verdict, detail)
        for (project, dep), found in sorted(checked.items())
        for dep, registry, verdict, detail in found
    ]
    registry_file = root / "projects" / "templates.yml"
    missing = [source for source in SOURCE_RE.findall(registry_file.read_text()) if not (root / source).is_dir()]
    return rows + [(source, "templates.yml", "missing", "the registry names a template source that is not on disk") for source in missing]


##### INFRA #####


def infra_rows(root: Path, token: str) -> list[Row]:
    """Findings over the action pins in the CI library: behind a release, or pinned to a branch."""
    pins = {
        (match.group(1), match.group(3))
        for path in [*sorted((root / "infra" / "jobs").rglob("*.yml")), *sorted((root / "infra" / "workflows").rglob("*.yml"))]
        for match in USES_RE.finditer(path.read_text())
    }
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        latest = dict(pool.map(lambda pin: (pin, _get(f"https://api.github.com/repos/{pin[0]}/releases/latest", token) or {}), pins))
    return [
        (f"{dep} {version}", "github", "behind" if version.startswith("v") else "branch-pin", f"latest upstream release is {tag}")
        for (dep, version), release in sorted(latest.items())
        if (tag := release.get("tag_name", "")) and tag != version
    ]


##### REPORT #####


def report(rows_by_area: dict[str, list[Row]]) -> str:
    """The Markdown body: one section per area, one four-column table each, an alive row when empty."""
    parts = ["Monthly health of the three areas — stack images, system dependencies, action pins.", ""]
    for area, rows in rows_by_area.items():
        parts += [f"## {area}", "", "| Subject | Source | Verdict | Detail |", "|---|---|---|---|"]
        parts += [f"| {subject} | {source} | {verdict} | {detail} |" for subject, source, verdict, detail in rows] or ["| — | — | alive | no findings |"]
        parts.append("")
    return "\n".join(parts) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--token", default="")
    args = parser.parse_args()
    areas = {"stack": stack_rows(args.root), "projects": projects_rows(args.root, args.token), "infra": infra_rows(args.root, args.token)}
    args.output.write_text(report(areas))
    total = sum(len(rows) for rows in areas.values())
    print(f"{total} findings across stack · projects · infra")
    return FINDINGS_EXIT if total else 0


if __name__ == "__main__":
    sys.exit(main())
