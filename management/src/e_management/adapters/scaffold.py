"""adapters.scaffold: the filesystem executor — a Plan becomes a tree, and drift answers whether a system still matches its sources."""

import re
import shutil
from typing import TYPE_CHECKING

from e_management.core.plan import Action, Copy, Generate, Materialize, Plan, PrunePaths, PruneTexts, Rename
from e_management.ops.rewrite import rewrite_segment, rewrite_text

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from e_management.models.manifest import Template

##### DEFAULTS #####
SKIP: frozenset[str] = frozenset(
    {".venv", "__pycache__", ".pytest_cache", ".ruff_cache", ".hypothesis", ".benchmarks", ".ty_cache", "site", "data"}
)


##### TYPES #####
class Scaffold:
    """Applies plans and checks drift for one repository root."""

    __slots__ = ("root",)

    def __init__(self, root: Path) -> None:
        self.root = root

    ##### PRIVATE #####

    def _fs_text(self, path: Path) -> str | None:
        try:
            return path.read_text()
        except SyntaxError, ValueError:
            return None

    def _fs_files(self, base: Path) -> Iterator[Path]:
        return (p for p in sorted(base.rglob("*")) if p.is_file() and not SKIP.intersection(p.parts))

    def _fs_tree(self, base: Path, excludes: tuple[str, ...] = ()) -> dict[str, Path]:
        tree = {p.relative_to(base).as_posix(): p for p in self._fs_files(base)} if base.is_dir() else {}
        return {name: path for name, path in tree.items() if name not in excludes}

    def _apply_action(self, action: Action, dest: Path) -> None:
        match action:
            case Copy():
                shutil.copytree(self.root / action.src, dest, ignore=lambda _d, n: SKIP & set(n))
                for drop in action.drops:
                    self._apply_prune_path(dest / drop)
            case Materialize():
                self._apply_materialize(action, dest)
            case PrunePaths():
                for path in action.paths:
                    self._apply_prune_path(dest / path)
            case PruneTexts():
                for prune in action.prunes:
                    self._apply_prune_text(dest / prune.file, prune.pattern, prune.to)
            case Rename():
                self._apply_rename(action, dest)
            case Generate():
                for generated in action.files:
                    out = dest / generated.path
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_text(generated.content)

    def _apply_prune_path(self, target: Path) -> None:
        shutil.rmtree(target) if target.is_dir() else target.unlink(missing_ok=True)

    def _apply_materialize(self, action: Materialize, dest: Path) -> None:
        src = self.root / action.src
        if src.is_file():
            out = dest / action.dst
            out.parent.mkdir(parents=True, exist_ok=True)
            self._fs_copy(src, out, action)
            return
        base = dest / action.dst
        shutil.rmtree(base, ignore_errors=True)
        for rel, path in self._fs_tree(src, action.excludes).items():
            out = base / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            self._fs_copy(path, out, action)

    def _fs_copy(self, src: Path, dst: Path, material: Materialize) -> None:
        text = self._fs_text(src)
        if text is None:
            shutil.copy2(src, dst)
        else:
            dst.write_text(rewrite_text(text, material.strip))

    def _apply_prune_text(self, file: Path, pattern: str, to: str = "") -> None:
        if (text := self._fs_text(file)) is not None and (out := re.sub(pattern, to, text, flags=re.MULTILINE)) != text:
            file.write_text(out)

    def _apply_rename(self, action: Rename, dest: Path) -> None:
        for path in self._fs_files(dest):
            if (text := self._fs_text(path)) is not None and (out := rewrite_text(text, action.rules)) != text:
                path.write_text(out)
        for path in sorted(dest.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            if (
                not SKIP.intersection(path.parts)
                and (fresh := path.with_name(rewrite_segment(path.name, action.rules))) != path
            ):
                path.rename(fresh)

    def _drift_pair(
        self, src: Path, dst: Path, excludes: tuple[str, ...] = ()
    ) -> tuple[dict[str, Path], dict[str, Path]]:
        """The two trees a material compares: source vs what the system holds, keyed by relative name."""
        if src.is_file():
            return {dst.name: src}, {dst.name: dst} if dst.exists() else {}
        return self._fs_tree(src, excludes), self._fs_tree(dst)

    ##### PUBLIC #####

    def apply(self, plan: Plan, dest: Path) -> Path:
        """Executes the whole plan, in order; the destination must not exist yet."""
        if dest.exists():
            msg = f"destination exists, refusing to overwrite: {dest}"
            raise FileExistsError(msg)
        dest.parent.mkdir(parents=True, exist_ok=True)
        for action in plan.actions:
            self._apply_action(action, dest)
        return dest

    def drift(self, template: Template) -> list[str]:
        """Problems between a system and its material sources: missing, extra or stale files. Empty means in sync."""
        issues: list[str] = []
        system = self.root / template.source
        for material in template.materials:
            src = self.root / material.src
            expected, actual = self._drift_pair(src, system / material.dst, material.excludes)
            issues += [f"{material.dst}:{name}: missing" for name in expected.keys() - actual]
            issues += [f"{material.dst}:{name}: extra" for name in actual.keys() - expected]
            for name in sorted(expected.keys() & actual.keys()):
                text = self._fs_text(expected[name])
                want = rewrite_text(text, material.strip) if text is not None else expected[name].read_bytes()
                got = actual[name].read_text() if text is not None else actual[name].read_bytes()
                if want != got:
                    issues.append(f"{material.dst}:{name}: stale")
        return issues
