""".github/tools/changelog.py: per-branch changelog fragments, folded into the single CHANGELOG.md. Deterministic, idempotent.

Two branches never touch the same file: a change is recorded in `.changelog.d/<branch, / as ->.md` (bullets,
optionally under `### stack|projects|infra` areas), and after every merge to main a bot PR folds every fragment
into `## [Unreleased]` of CHANGELOG.md and deletes it. Fragments fold oldest first (date of the commit that
added them). Areas are kept where CHANGELOG.md already uses them; otherwise the bullets go in plain.
Everything below the Unreleased block is the humans' territory and untouched.
Stdlib only, like every house tool that must run anywhere."""

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Final

AREAS: Final = ("stack", "projects", "infra")
UNRELEASED: Final = "## [Unreleased]"
FRAGMENTS: Final = ".changelog.d"
GUIDE: Final = "README.md"
HEADER: Final = "# Changelog\n"
AREA_HEADING: Final = re.compile(rf"^### ({'|'.join(AREAS)})$", re.MULTILINE)
Sections = list[tuple[str | None, list[str]]]


def slug(branch: str) -> str:
    """The fragment name of a branch: `feat/base-root` -> `feat-base-root`."""
    return branch.replace("/", "-")


def _parse(text: str) -> Sections:
    """Bullets of a fragment grouped by area, file order kept; a bullet keeps its wrapped continuation lines."""
    sections: Sections = [(None, [])]
    for line in text.splitlines():
        if heading := re.fullmatch(r"### (\S+)", line):
            sections.append((heading.group(1), []))
        elif line.startswith("- "):
            sections[-1][1].append(line)
        elif line.startswith((" ", "\t")) and sections[-1][1]:
            sections[-1][1][-1] += f"\n{line}"
    return [(area, items) for area, items in sections if items]


def _render(sections: Sections) -> str:
    return "\n".join(
        (f"### {area}\n\n" if area else "") + "\n".join(items) + "\n" for area, items in sections
    )


def record(text: str, area: str | None, line: str) -> str:
    """The fragment after one bullet is recorded under its area — identical text if it is already there."""
    bullet = f"- {line}"
    sections = _parse(text)
    if any(bullet in items for found, items in sections if found == area):
        return text
    merged = [(found, [*items, bullet] if found == area else items) for found, items in sections]
    return _render(merged if any(found == area for found, _ in merged) else [*merged, (area, [bullet])])


def _append(body: list[str], items: list[str]) -> list[str]:
    """Items added after the last content line of a block of lines, a blank line separating them from a heading."""
    content = list(body)
    while content and not content[-1].strip():
        content.pop()
    spacer = [""] if content and (content[-1].startswith("#") or items[0].startswith("#")) else []
    return [*content, *spacer, *[line for item in items for line in item.split("\n")]]


def _place(block: list[str], area: str | None, items: list[str]) -> list[str]:
    """The Unreleased block after adding items: into their area section if the file uses areas (area-less ones above the first area), else at its end."""
    heads = [i for i, line in enumerate(block) if AREA_HEADING.match(line)]
    if not heads:
        return _append(block, items)
    if area is None:
        return [*_append(block[: heads[0]], items), "", *block[heads[0] :]]
    if (at := next((i for i in heads if block[i] == f"### {area}"), None)) is None:
        return _append(block, [f"### {area}", "", *items])
    end = next((i for i in range(at + 1, len(block)) if block[i].startswith("### ")), len(block))
    return [*block[:at], *_append(block[at:end], items), "", *block[end:]]


def fold(text: str, fragments: list[str]) -> str:
    """The changelog with every fragment's bullets folded under Unreleased, in the order given; known bullets skipped."""
    if not fragments:
        return text
    head, marker, rest = text.partition(UNRELEASED)
    if not marker:
        top, sep, tail = text.partition("\n## ")
        head, rest = f"{top.rstrip()}\n\n", f"\n\n{'## ' + tail if sep else ''}"
    body, sep, tail = rest.partition("\n## ")
    block = body.strip("\n").split("\n") if body.strip() else []
    present = body
    for fragment in fragments:
        for area, items in _parse(fragment):
            fresh = [item for item in items if item not in present]
            block = _place(block, area, fresh) if fresh else block
            present += "\n".join(fresh)
    return f"{head}{UNRELEASED}\n\n" + "\n".join(block).strip("\n") + "\n" + (f"\n## {tail}" if sep else "")


def _first_commit(root: Path, path: Path) -> int:
    """Unix time of the commit that added the fragment; the file's mtime when git does not know it yet."""
    out = subprocess.run(
        ["git", "-C", str(root), "log", "--diff-filter=A", "--format=%ct", "--", str(path.relative_to(root))],
        capture_output=True, text=True, check=False,
    ).stdout.split()
    return int(out[-1]) if out else int(path.stat().st_mtime)


def _fragments(root: Path) -> list[Path]:
    """Every fragment, oldest first; ties by name."""
    found = [p for p in (root / FRAGMENTS).glob("*.md") if p.name != GUIDE]
    return sorted(found, key=lambda p: (_first_commit(root, p), p.name))


def _branch(root: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)
    rec = commands.add_parser("record", help="add one bullet to the current branch's fragment")
    rec.add_argument("--area", choices=AREAS)
    rec.add_argument("--line", required=True)
    rec.add_argument("--branch", help="the branch to name the fragment after (default: the checked-out one)")
    commands.add_parser("fold", help="fold every fragment into CHANGELOG.md and delete it")
    args = parser.parse_args()
    root: Path = args.root
    if args.command == "record":
        path = root / FRAGMENTS / f"{slug(args.branch or _branch(root))}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(record(path.read_text() if path.is_file() else "", args.area, args.line))
        return 0
    paths = _fragments(root)
    if not paths:
        return 0
    changelog = root / "CHANGELOG.md"
    changelog.write_text(fold(changelog.read_text() if changelog.is_file() else HEADER, [p.read_text() for p in paths]))
    [p.unlink() for p in paths]
    return 0


if __name__ == "__main__":
    sys.exit(main())
