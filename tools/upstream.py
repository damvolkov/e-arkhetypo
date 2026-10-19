"""tools/upstream.py: what a Renovate PR actually changed — the release facts between old and new.

Stdlib only. Diffs the dependency pins of two pyproject.toml files and, for each moved package, writes
into the output directory: `versions.txt` (old→new per line), `release-notes.md` (the GitHub releases
between the two tags, when reachable) and an empty `api-added.txt` — the file maintenance reads to decide
whether there is an `expose` to do. Exit 0 always: context is never a failure; a missing package is a
line saying so."""

import argparse
import json
import re
import sys
import tomllib
import urllib.request
from pathlib import Path
from typing import Any

NAME_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")
TIMEOUT = 30


def pins(path: Path) -> dict[str, str]:
    """package → declared spec, for every dependency the file names."""
    data = tomllib.loads(path.read_text())
    sources = [data.get("project", {}).get("dependencies") or (), *data.get("optional-dependencies", {}).values(), *data.get("dependency-groups", {}).values()]
    found: dict[str, str] = {}
    for dep in (str(dep) for group in sources for dep in group):
        if match := NAME_RE.match(dep):
            version = next(iter(re.findall(r"[><=~^]=?\s*([0-9][^,;)]*)", dep)), "")
            found[match.group(1).lower()] = version.strip()
    return found


def _get(url: str, token: str = "") -> Any:
    """A JSON GET with the house identity; anything ungraceful answers None — context is optional."""
    headers = {"User-Agent": "e-stack-upstream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=TIMEOUT) as response:
            return json.load(response)
    except Exception:  # noqa: BLE001 — a failed note fetch is a missing note, never a failed run
        return None


def notes_for(package: str, new: str, token: str) -> str:
    """The newest release entry mentioning `new`, from the package's declared GitHub repository."""
    info = (_get(f"https://pypi.org/pypi/{package}/json") or {}).get("info") or {}
    repo = next(
        (re.search(r"github\.com/([^/]+/[^/.]+)", str(link or "")).group(1) for link in (info.get("project_urls") or {}).values() if link and re.search(r"github\.com/([^/]+/[^/.]+)", str(link))),
        "",
    )
    release = _get(f"https://api.github.com/repos/{repo}/tags?per_page=100", token) if repo else None
    tag = next((t["name"] for t in release or () if new in t["name"]), f"v{new}")
    body = _get(f"https://api.github.com/repos/{repo}/releases/tags/{tag}", token) if repo else None
    return f"## {package} {new}\n\n{body.get('body', '')}" if body else f"## {package} {new}\n\n_No release notes found (repo: {repo or 'unknown'}, tag: {tag})._\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--head", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--token", default="")
    args = parser.parse_args()
    before, after = pins(args.base), pins(args.head)
    moved = {name: (old, after[name]) for name, old in before.items() if name in after and after[name] != old}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "versions.txt").write_text("\n".join(f"{name}: {old} -> {new}" for name, (old, new) in sorted(moved.items())) + "\n")
    (args.output / "release-notes.md").write_text("\n\n".join(notes_for(name, new, args.token) for name, (_, new) in sorted(moved.items())) + "\n")
    (args.output / "api-added.txt").write_text("")
    print(f"{len(moved)} dependencies moved")
    return 0


if __name__ == "__main__":
    sys.exit(main())
