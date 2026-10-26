""".github/tools/health.py: dependency health — archived, vanished, stale or dormant upstreams, as a Markdown report.

Stdlib only, like every house tool that must run anywhere. Reads pyproject.toml (project deps and
dependency-groups), probes PyPI for each package and, through the project's declared URLs, GitHub for
the repository. Exit 0: everything alive. Exit 3: findings — the contract the workflow reads. Any other
failure is the probe's own error."""

import argparse
import concurrent.futures
import json
import re
import sys
import time
import tomllib
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

FINDINGS_EXIT = 3
STALE_DAYS = 540
DORMANT_DAYS = 365
CONCURRENCY = 8
TIMEOUT = 30
USER_AGENT = "e-stack-health"
NAME_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")
DIGITS_RE = re.compile(r"\d+")


def version_key(version: str) -> tuple[tuple[int, ...], int]:
    """A release string as a sortable key: numbers compare numerically, a suffix (pre-release) loses ties."""
    return (tuple(int(part) for part in DIGITS_RE.findall(version)), -len(re.sub(r"[\d.]", "", version)))

RULES = ("archived", "vanished", "stale", "dormant")


def requirements(root: Path) -> list[str]:
    """Every named dependency of the project, minus its spec, deduped, sorted — self-excluded."""
    data = tomllib.loads((root / "pyproject.toml").read_text())
    sources = [data.get("project", {}).get("dependencies") or (), *data.get("optional-dependencies", {}).values(), *data.get("dependency-groups", {}).values()]
    names = [m.group(1) for group in sources for dep in group for m in [NAME_RE.match(str(dep))] if m]
    if project := data.get("project", {}).get("name"):
        names = [n for n in names if n.lower().replace("_", "-") != project.lower().replace("_", "-")]
    return sorted(dict.fromkeys(names))


def _get(url: str, token: str) -> Any:
    """A JSON GET with the house identity; a 404 answers None — vanished is a finding, not a crash."""
    headers = {"User-Agent": USER_AGENT}
    if token and url.startswith("https://api.github.com/"):
        headers["Authorization"] = f"Bearer {token}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=TIMEOUT) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise
    except TimeoutError:
        raise TimeoutError(f"timeout: {url}") from None


def _repo_of(name: str, token: str) -> str | None:
    """The GitHub repository a package declares, through PyPI's project URLs."""
    urls = _get(f"https://pypi.org/pypi/{name}/json", "").get("info", {}).get("project_urls") or {}
    for link in urls.values():
        if owner_repo := next(iter(re.findall(r"github\.com/([^/]+/[^/]+)", str(link or ""))), ""):
            return owner_repo.removesuffix(".git").removesuffix("/")
    return None


def check(name: str, token: str) -> list[tuple[str, str, str, str]]:
    """One package's findings as (dependency, registry, verdict, detail) rows — empty means alive."""
    pypi = _get(f"https://pypi.org/pypi/{name}/json", "")
    if pypi is None:
        return [(name, "PyPI", "vanished", "package is gone from the index")]
    latest = max(pypi["releases"], key=version_key, default="")
    uploaded = (pypi["releases"].get(latest) or [{}])[0].get("upload_time", "")
    age = (time.time() - time.mktime(time.strptime(uploaded, "%Y-%m-%dT%H:%M:%S"))) / 86400 if uploaded else STALE_DAYS + 1
    rows = [(name, "PyPI", "stale", f"last release {latest} is {int(age)} days old")] if age > STALE_DAYS else []
    if (repo := _repo_of(name, token)) is not None:
        meta = _get(f"https://api.github.com/repos/{repo}", token) or {}
        pushed = (meta.get("pushed_at") or "")[:10]
        since = (time.time() - time.mktime(time.strptime(pushed, "%Y-%m-%d"))) / 86400 if pushed else 0
        rows += [(name, f"github:{repo}", "archived", "the repository is archived")] if meta.get("archived") else []
        rows += [(name, f"github:{repo}", "dormant", f"no push in {int(since)} days")] if since > DORMANT_DAYS else []
    return rows


def report(root: Path, token: str) -> tuple[list[str], int, int]:
    """The Markdown table rows plus (checked, findings) counts — probes run concurrently off the main thread."""
    deps = requirements(root)
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        found = [row for rows in pool.map(lambda name: check(name, token), deps) for row in rows]
    lines = [f"| Dependency | Registry | Verdict | Detail |", "|---|---|---|---|"]
    lines += [f"| {name} | {registry} | {verdict} | {detail} |" for name, registry, verdict, detail in found]
    return lines, len(deps), len(found)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--token", default="", help="GitHub token — raises the API rate limit")
    args = parser.parse_args()
    lines, checked, findings = report(args.root, args.token)
    args.output.write_text("\n".join(lines) + "\n")
    print(f"{checked} dependencies checked, {findings} findings")
    return FINDINGS_EXIT if findings else 0


if __name__ == "__main__":
    sys.exit(main())
