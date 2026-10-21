"""tools/changelog.py: append one maintenance line to an area section under [Unreleased]. Deterministic, idempotent.

The record of every bot sync and human change in a wide repo: one CHANGELOG.md, three areas
(stack · projects · infra) under a single `## [Unreleased]` heading. This tool inserts one bullet as
the first line of its area section, creating the heading on demand; an identical line already
present is a no-op. Everything below the Unreleased block is the humans' territory and untouched.
Stdlib only, like every house tool that must run anywhere."""

import argparse
import re
import sys
from pathlib import Path
from typing import Final

AREAS: Final = ("stack", "projects", "infra")
UNRELEASED: Final = "## [Unreleased]"
SECTION: Final = re.compile(r"^(### (stack|projects|infra))\n(.*?)(?=^### |^## |\Z)", re.MULTILINE | re.DOTALL)


def _areas(body: str) -> dict[str, list[str]]:
    """The area bullets inside the Unreleased body, keyed by area name, file order kept outside."""
    return {match.group(2): [line for line in match.group(3).splitlines() if line.startswith("- ")] for match in SECTION.finditer(body)}


def record(text: str, area: str, line: str) -> str:
    """The changelog after recording one bullet under its area — identical text if it is already there."""
    bullet = f"- {line}"
    before, _, rest = text.partition(UNRELEASED)
    if not rest:
        before, rest = text, f"\n\n{UNRELEASED}\n"
    head, _, tail = rest.partition("\n## ")
    found = _areas(head)
    if bullet in found.get(area, ()):
        return text
    found.setdefault(area, [])
    found[area] = [bullet, *found[area]]
    rebuilt = "".join(f"### {name}\n\n{chr(10).join(found[name])}\n\n" for name in AREAS)
    return f"{before}{UNRELEASED}\n\n{rebuilt}{f'## {tail}' if tail else ''}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--area", required=True, choices=AREAS)
    parser.add_argument("--line", required=True)
    args = parser.parse_args()
    path = args.root / "CHANGELOG.md"
    text = path.read_text() if path.is_file() else "# Changelog\n\nMaintenance record: every sync, bump and repair, filed under the area it touched.\n"
    path.write_text(record(text, args.area, args.line))
    return 0


if __name__ == "__main__":
    sys.exit(main())
