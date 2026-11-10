"""gates/engine: the engine of the gates — reads `gates/rules.yml`, runs every rule at its level and reports each violation,
for a commit's files (prek passes them) or for the whole tree (no files: CI, `make gates`).

`tree` and `shape` are read here, from the paths and the stdlib `ast`; `syntax` rules are handed to ast-grep inline,
one run for all; `genealogy` and `parity` import the project, so the unit suite runs them, never a commit hook.

    python -m gates.engine check [paths...]   tree, shape, syntax; with paths, only the violations at those paths
    python -m gates.engine semantic           genealogy, parity
    python -m gates.engine test               every syntax rule against its own valid and invalid cases"""

import ast
import importlib
import inspect
import json
import re
import shutil
import subprocess
import sys
import tempfile
from fnmatch import fnmatchcase
from itertools import chain
from pathlib import Path, PurePosixPath
from types import FunctionType, MappingProxyType, ModuleType
from typing import TYPE_CHECKING, Any, Final

import eserde

from gates.models import (
    Classes,
    Constants,
    Functions,
    GateError,
    Gates,
    Genealogy,
    Parity,
    Rule,
    Shape,
    Syntax,
    Tree,
    Violation,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence

RULES: Final = Path("gates/rules.yml")
SKIPPED: Final = frozenset({"__pycache__"})

##### LOAD #####


def gate_load(root: Path) -> Gates:
    """The project's rules, as `gates/rules.yml` writes them."""
    return eserde.load(root / RULES, type=Gates)


def gate_select[R: Rule](gates: Gates, kind: type[R]) -> list[R]:
    """The rules of one level, in the file's order."""
    return [rule for rule in gates.rules if isinstance(rule, kind)]


##### PATHS #####


def gate_relative(path: Path, root: Path) -> str:
    """A path as the rules and the reports spell it: POSIX, relative to the root."""
    return path.relative_to(root).as_posix()


def gate_matches(path: str, globs: Iterable[str]) -> bool:
    """Whether a relative path matches any of the globs, `**` spanning directories."""
    return any(PurePosixPath(path).full_match(glob) for glob in globs)


def gate_files(root: Path, globs: Iterable[str], ignores: Iterable[str]) -> list[Path]:
    """Every file the globs select and the ignores do not, once each, in path order."""
    return sorted(
        {
            path
            for glob in globs
            for path in root.glob(glob)
            if path.is_file() and not gate_matches(gate_relative(path, root), ignores)
        }
    )


def gate_report(rule: Rule, path: str, line: int, detail: str) -> Violation:
    """The violation of a rule at a place, its message followed by what was found."""
    return Violation(path=path, line=line, rule=rule.id, law=rule.law, message=f"{rule.message} ({detail})")


##### TREE #####


def gate_entries(directory: Path) -> dict[str, Path]:
    """A directory's entries by the name the rules match: a subdirectory with a trailing `/`."""
    return {
        f"{entry.name}/" if entry.is_dir() else entry.name: entry
        for entry in directory.iterdir()
        if entry.name not in SKIPPED
    }


def gate_tree(rule: Tree, root: Path) -> Iterator[Violation]:
    """What each directory holds against what the rule allows and requires."""
    directories = sorted(
        {
            path
            for glob in rule.dirs
            for path in root.glob(glob)
            if path.is_dir()
            and SKIPPED.isdisjoint(path.parts)
            and not gate_matches(gate_relative(path, root), rule.ignores)
        }
    )
    held = [(directory, gate_entries(directory)) for directory in directories]
    strangers = (
        gate_report(rule, gate_relative(path, root), 1, f"{name} is not one of {list(rule.allow)}")
        for _, entries in held
        for name, path in entries.items()
        if rule.allow is not None and not any(fnmatchcase(name, glob) for glob in rule.allow)
    )
    missing = (
        gate_report(rule, gate_relative(directory, root), 1, f"{glob} is required here")
        for directory, entries in held
        for glob in rule.require
        if not any(fnmatchcase(name, glob) for name in entries)
    )
    return chain(strangers, missing)


##### SHAPE #####


def gate_pascal(name: str) -> str:
    """A directory's name in PascalCase: `paraphrase` → `Paraphrase`, `ask_user` → `AskUser`."""
    return "".join(part.capitalize() for part in name.split("_"))


def gate_base(base: ast.expr) -> str:
    """A base class's bare name: `infra.node.GuardrailNode[X]` → `GuardrailNode`."""
    return ast.unparse(base).split("[")[0].rsplit(".", 1)[-1]


def gate_classes(rule: Shape, spec: Classes, path: str, module: ast.Module, directory: str) -> Iterator[Violation]:
    """The module's classes against how many, how named and inheriting from what."""
    classes = [node for node in module.body if isinstance(node, ast.ClassDef)]
    name = spec.name.replace("{Dir}", gate_pascal(directory))
    counted = (
        (gate_report(rule, path, 1, f"{len(classes)} classes, {spec.count} allowed"),)
        if spec.count is not None and len(classes) != spec.count
        else ()
    )
    named = (
        gate_report(rule, path, node.lineno, f"class {node.name} is not named {name}")
        for node in classes
        if not fnmatchcase(node.name, name)
    )
    based = (
        gate_report(rule, path, node.lineno, f"class {node.name} has no base named {spec.bases}")
        for node in classes
        if spec.bases is not None and not any(fnmatchcase(gate_base(base), spec.bases) for base in node.bases)
    )
    return chain(counted, named, based)


def gate_functions(rule: Shape, spec: Functions, path: str, module: ast.Module) -> Iterator[Violation]:
    """The module's top-level functions against how many, and whether each is `async`."""
    functions = [node for node in module.body if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)]
    counted = (
        gate_report(rule, path, node.lineno, f"function {node.name} beyond the {spec.max} allowed")
        for node in functions[spec.max :]
        if spec.max is not None
    )
    blocking = (
        gate_report(rule, path, node.lineno, f"function {node.name} is not async")
        for node in functions
        if spec.asynchronous and isinstance(node, ast.FunctionDef)
    )
    return chain(counted, blocking)


def gate_literal(value: ast.expr | None) -> bool:
    """Whether a string literal appears anywhere in a value."""
    return value is not None and any(
        isinstance(node, ast.Constant) and isinstance(node.value, str) for node in ast.walk(value)
    )


def gate_constants(rule: Shape, spec: Constants, path: str, module: ast.Module) -> Iterator[Violation]:
    """The module's top-level assignments against how many, annotated how, and holding text or not."""
    assigned = [node for node in module.body if isinstance(node, ast.Assign | ast.AnnAssign)]
    annotations = [(node, ast.unparse(node.annotation) if isinstance(node, ast.AnnAssign) else "") for node in assigned]
    counted = (
        gate_report(rule, path, node.lineno, f"constant beyond the {spec.max} allowed")
        for node in assigned[spec.max :]
        if spec.max is not None
    )
    annotated = (
        gate_report(rule, path, node.lineno, f"annotation {annotation or 'none'} is not {spec.annotation}")
        for node, annotation in annotations
        if not re.fullmatch(spec.annotation, annotation)
    )
    texts = (
        gate_report(rule, path, node.lineno, "a string literal in a constant")
        for node in assigned
        if not spec.literals and gate_literal(node.value)
    )
    return chain(counted, annotated, texts)


def gate_module(rule: Shape, root: Path, file: Path) -> Iterator[Violation]:
    """One module's top level against every part of the shape the rule names."""
    path, module = gate_relative(file, root), ast.parse(file.read_text(encoding="utf-8"))
    return chain(
        gate_classes(rule, rule.classes, path, module, file.parent.name) if rule.classes else (),
        gate_functions(rule, rule.functions, path, module) if rule.functions else (),
        gate_constants(rule, rule.constants, path, module) if rule.constants else (),
    )


def gate_shape(rule: Shape, root: Path) -> Iterator[Violation]:
    """Every module the rule selects, against its shape."""
    return chain.from_iterable(gate_module(rule, root, file) for file in gate_files(root, rule.files, rule.ignores))


##### SYNTAX #####


def gate_binary() -> str:
    """The ast-grep binary of the environment."""
    match shutil.which("ast-grep"):
        case str() as binary:
            return binary
        case None:
            msg = "ast-grep is not installed: `uv add --dev ast-grep-cli`"
            raise GateError(msg)


def gate_inline(rule: Syntax, files: Sequence[str], ignores: Sequence[str]) -> dict[str, Any]:
    """A syntax rule as ast-grep reads it, scoped to the files given."""
    written = {
        "id": rule.id,
        "language": "python",
        "severity": "error",
        "message": rule.message,
        "metadata": {"law": rule.law},
        "files": list(files),
        "ignores": list(ignores),
        "rule": rule.rule,
        "constraints": rule.constraints,
    }
    return {key: value for key, value in written.items() if value not in (None, [])}


def gate_grep(root: Path, rules: Sequence[dict[str, Any]], paths: Sequence[str]) -> list[Violation]:
    """One ast-grep run of every rule over the paths: each match a violation; a broken run raises."""
    match rules, paths:
        case ([], _) | (_, []):
            return []
        case _:
            run = subprocess.run(
                [
                    gate_binary(),
                    "scan",
                    "--inline-rules",
                    "\n---\n".join(json.dumps(rule) for rule in rules),
                    "--json=stream",
                    "--include-metadata",
                    *paths,
                ],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )
    matches = [json.loads(line) for line in run.stdout.splitlines() if line.strip()]
    match run.returncode, matches:
        case (0, []) | (1, [_, *_]):
            return [
                Violation(
                    path=found["file"],
                    line=found["range"]["start"]["line"] + 1,
                    rule=found["ruleId"],
                    law=found["metadata"]["law"],
                    message=found["message"],
                )
                for found in matches
            ]
        case _:
            raise GateError(run.stderr or run.stdout)


def gate_syntax(root: Path, gates: Gates) -> list[Violation]:
    """Every match of every syntax rule over the roots."""
    rules = [gate_inline(rule, rule.files, rule.ignores) for rule in gate_select(gates, Syntax)]
    return gate_grep(root, rules, [name for name in gates.roots if (root / name).exists()])


def gate_cases(gates: Gates) -> Iterator[Violation]:
    """Every syntax rule against its cases, in one run: a valid case it catches, an invalid one it misses."""
    rules = gate_select(gates, Syntax)
    cases = [
        (rule, f"{rule.id}/{kind}-{index}.py", code, kind)
        for rule in rules
        for kind, codes in (("valid", rule.valid), ("invalid", rule.invalid))
        for index, code in enumerate(codes)
    ]
    with tempfile.TemporaryDirectory() as scratch:
        _ = [
            (Path(scratch) / name).parent.mkdir(parents=True, exist_ok=True) or (Path(scratch) / name).write_text(code)
            for _, name, code, _ in cases
        ]
        caught = {
            violation.path
            for violation in gate_grep(
                Path(scratch), [gate_inline(rule, [f"{rule.id}/**"], []) for rule in rules], ["."]
            )
        }
    return (
        gate_report(rule, str(RULES), 1, f"{kind} case {'caught' if kind == 'valid' else 'missed'}: {code!r}")
        for rule, name, code, kind in cases
        if (name in caught) == (kind == "valid")
    )


##### GENEALOGY #####


def gate_dotted(file: Path, root: Path) -> str:
    """A module's import name from its path: `src/aivo_agents/ops/text.py` → `aivo_agents.ops.text`."""
    parts = file.relative_to(root).with_suffix("").parts
    return ".".join(parts[1:] if parts[0] == "src" else parts)


def gate_dunder(name: str) -> bool:
    """Whether a name is a dunder or a sunder (`__init__`, `_missing_`): the language's, never the class's own."""
    return len(name) > 2 and name.startswith("_") and name.endswith("_")  # noqa: PLR2004 — the two underscores


def gate_method(value: object) -> FunctionType | None:
    """The function behind a class attribute — plain, static, class method or property getter — or None."""
    inner = getattr(value, "__func__", None) or getattr(value, "fget", None) or value
    return inner if inspect.isfunction(inner) else None


def gate_written(cls: type, method: FunctionType) -> bool:
    """Whether a method's code is in its class's module file, not generated into it (`NamedTuple._make`)."""
    return method.__code__.co_filename == getattr(sys.modules[cls.__module__], "__file__", None)


def gate_publics(cls: type) -> tuple[str, ...]:
    """The names a private method may serve: every public method of the class, and every dunder it answers, by stem —
    `__call__` → `call`; an async one by its stem too, `__aenter__` → `aenter`, `enter`."""
    methods = [name for name in dir(cls) if gate_method(inspect.getattr_static(cls, name))]
    stems = [name.strip("_") for name in methods if name.startswith("__")]
    return (
        *(name for name in methods if not name.startswith("_")),
        *stems,
        *(stem.removeprefix("a") for stem in stems if stem.startswith("a")),
    )


def gate_foreign(cls: type, name: str, ours: frozenset[str]) -> bool:
    """Whether a name overrides a base defined outside the selected modules: the framework's contract, not the class's."""
    return any(name in vars(base) for base in cls.__mro__[1:] if base.__module__ not in ours)


def gate_lineage(rule: Genealogy, cls: type, path: str, ours: frozenset[str]) -> Iterator[Violation]:
    """Every private method of a class that names no public method of it and is not `_common_`; with `order`, every
    private one listed after the first public one."""
    publics = gate_publics(cls)
    methods = [
        (name, method)
        for name, value in vars(cls).items()
        if not gate_dunder(name)
        and not gate_foreign(cls, name, ours)
        and (method := gate_method(value))
        and gate_written(cls, method)
    ]
    first = next((index for index, (name, _) in enumerate(methods) if not name.startswith("_")), len(methods))
    orphans = (
        gate_report(rule, path, inspect.getsourcelines(method)[1], f"{cls.__name__}.{name} serves no public method")
        for name, method in methods
        if name.startswith("_") and not name.startswith(("_common_", *(f"_{public}_" for public in publics)))
    )
    late = (
        gate_report(rule, path, inspect.getsourcelines(method)[1], f"{cls.__name__}.{name} after a public method")
        for name, method in methods[first:]
        if rule.order and name.startswith("_")
    )
    return chain(orphans, late)


def gate_import(file: Path, root: Path) -> ModuleType | ImportError:
    """A module imported from its path, or the error that kept it from importing."""
    try:
        return importlib.import_module(gate_dotted(file, root))
    except ImportError as error:
        return error


def gate_genealogy(rule: Genealogy, root: Path) -> Iterator[Violation]:
    """Every class the selected modules define, imported, against the genealogy of its private methods; a module that
    does not import is a violation of its own, never a crash of the run."""
    imported = [
        (gate_relative(file, root), gate_import(file, root)) for file in gate_files(root, rule.files, rule.ignores)
    ]
    modules = [(path, module) for path, module in imported if isinstance(module, ModuleType)]
    broken = (
        gate_report(rule, path, 1, f"does not import: {error}")
        for path, error in imported
        if isinstance(error, ImportError)
    )
    ours = frozenset(module.__name__ for _, module in modules)
    return chain(
        broken,
        chain.from_iterable(
            gate_lineage(rule, value, path, ours)
            for path, module in modules
            for value in vars(module).values()
            if inspect.isclass(value) and value.__module__ == module.__name__
        ),
    )


##### PARITY #####


def gate_parity(rule: Parity, root: Path) -> Iterator[Violation]:
    """The enum's values and the files' stems: each side's strangers to the other."""
    module, name = rule.enum.split(":")
    members = {str(member.value) for member in getattr(importlib.import_module(module), name)}
    files = {path.stem: gate_relative(path, root) for path in root.glob(rule.files)}
    return chain(
        (gate_report(rule, rule.enum, 1, f"{member} has no file") for member in sorted(members - files.keys())),
        (gate_report(rule, files[stem], 1, f"{stem} is no member") for stem in sorted(files.keys() - members)),
    )


##### RUN #####


def gate_within(violation: Violation, paths: Sequence[str]) -> bool:
    """Whether a violation and one of the given paths contain each other (a file, a directory above it, a directory
    a violation names); no paths keeps every violation."""
    return not paths or any(
        violation.path == path or violation.path.startswith(f"{path}/") or path.startswith(f"{violation.path}/")
        for path in (str(each).rstrip("/") for each in paths)
    )


def gate_check(root: Path, paths: Sequence[str] = ()) -> list[Violation]:
    """Tree, shape and syntax over the project, kept to the given paths when there are any."""
    gates = gate_load(root)
    found = chain(
        chain.from_iterable(gate_tree(rule, root) for rule in gate_select(gates, Tree)),
        chain.from_iterable(gate_shape(rule, root) for rule in gate_select(gates, Shape)),
        gate_syntax(root, gates),
    )
    return sorted(violation for violation in found if gate_within(violation, paths))


def gate_semantic(root: Path) -> list[Violation]:
    """Genealogy and parity over the imported project."""
    gates = gate_load(root)
    return sorted(
        chain(
            chain.from_iterable(gate_genealogy(rule, root) for rule in gate_select(gates, Genealogy)),
            chain.from_iterable(gate_parity(rule, root) for rule in gate_select(gates, Parity)),
        )
    )


def gate_test(root: Path) -> list[Violation]:
    """Every syntax rule against its own cases."""
    return sorted(gate_cases(gate_load(root)))


def gate_print(violations: Sequence[Violation]) -> int:
    """The violations, one per line, and the exit code they make."""
    sys.stdout.writelines(f"{violation}\n" for violation in violations)
    return int(bool(violations))


COMMANDS: Final[Mapping[str, Callable[[Path, Sequence[str]], list[Violation]]]] = MappingProxyType(
    {
        "check": gate_check,
        "semantic": lambda root, _: gate_semantic(root),
        "test": lambda root, _: gate_test(root),
    }
)


def gate_main(argv: Sequence[str]) -> int:
    """`check [paths...]`, `semantic` or `test`, from the project root."""
    match argv:
        case [command, *paths] if command in COMMANDS:
            return gate_print(COMMANDS[command](Path.cwd(), paths))
        case _:
            sys.stderr.write(f"usage: python -m gates.engine {{{'|'.join(COMMANDS)}}} [paths...]\n")
            return 2


if __name__ == "__main__":
    sys.exit(gate_main(sys.argv[1:]))
