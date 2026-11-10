"""gates/models: the shape of `gates/rules.yml` — every rule no existing tool states by name, and the violation each
one reports.

What ruff, tach or prek already name (an import, `print`, `os.environ`, a layer, a forbidden file) lives in their own
configuration, never here. A rule here is a selector (globs over paths, relative to the root), an entity and an
assertion, at the cheapest level that sees it whole: `Tree` reads directories, `Shape` one module's top level through
`ast`, `Syntax` is an ast-grep rule with its own cases, `Genealogy` the imported classes, `Parity` an enum against the
files it names. The template's defaults come first in the file; the project's own follow."""

from collections.abc import Mapping

from msgspec import Struct

### ast-grep's own rule schema, handed through untouched: msgspec cannot analyse a recursive JSON alias (RecursionError).
type Verbatim = Mapping[str, object]  # ast-grep-ignore: object-annotation


class GateError(Exception):
    """A gate that could not run: a missing binary, a broken rule, a file that does not load."""


class Rule(Struct, frozen=True, forbid_unknown_fields=True, kw_only=True, tag_field="level"):
    """What every rule carries: its level (the tag), its id, the law it gates and what it says when broken."""

    id: str
    law: str
    message: str


class Tree(Rule, frozen=True, kw_only=True, tag="tree"):
    """What each directory matching `dirs` may hold (`allow`, None for anything) and must hold (`require`). Entries
    are globs over names; a subdirectory is named with a trailing `/`."""

    dirs: tuple[str, ...]
    ignores: tuple[str, ...] = ()
    allow: tuple[str, ...] | None = None
    require: tuple[str, ...] = ()


class Classes(Struct, frozen=True, forbid_unknown_fields=True, kw_only=True):
    """The classes a module may define: how many, named how (a glob, `{Dir}` its directory in PascalCase) and
    inheriting from at least one base whose name matches `bases`."""

    count: int | None = None
    name: str = "*"
    bases: str | None = None


class Functions(Struct, frozen=True, forbid_unknown_fields=True, kw_only=True):
    """The top-level functions a module may define: at most how many, and whether every one is `async`."""

    max: int | None = None
    asynchronous: bool = False


class Constants(Struct, frozen=True, forbid_unknown_fields=True, kw_only=True):
    """The top-level assignments a module may hold: at most how many, annotated how (a regular expression; `""` is no
    annotation), and whether a string literal may appear in their values."""

    max: int | None = None
    annotation: str = ".*"
    literals: bool = True


class Shape(Rule, frozen=True, kw_only=True, tag="shape"):
    """The top level of every module matching `files`: its classes, its functions and its constants."""

    files: tuple[str, ...]
    ignores: tuple[str, ...] = ()
    classes: Classes | None = None
    functions: Functions | None = None
    constants: Constants | None = None


class Syntax(Rule, frozen=True, kw_only=True, tag="syntax"):
    """An ast-grep rule (`rule`, `constraints`: its own YAML, verbatim) over the files matching `files`, with the
    snippets it must pass (`valid`) and must catch (`invalid`)."""

    files: tuple[str, ...]
    ignores: tuple[str, ...] = ()
    rule: Verbatim
    constraints: Verbatim | None = None
    valid: tuple[str, ...] = ()
    invalid: tuple[str, ...] = ()


class Genealogy(Rule, frozen=True, kw_only=True, tag="genealogy"):
    """Every private method of every class the modules matching `files` define is `_<public>_<what>` — `<public>` a
    public method or a dunder's stem (`__aenter__` → `aenter`, `enter`) — or `_common_<what>`; with `order`, the class
    lists its private methods before its public ones. An override of a base from outside the selected modules is the
    framework's contract (`_agenerate`), never judged."""

    files: tuple[str, ...]
    ignores: tuple[str, ...] = ()
    order: bool = False


class Parity(Rule, frozen=True, kw_only=True, tag="parity"):
    """The values of an enum (`module:Name`) and the stems of the files matching `files` are the same set."""

    enum: str
    files: str


class Gates(Struct, frozen=True, forbid_unknown_fields=True, kw_only=True):
    """`gates/rules.yml`: the roots ast-grep scans, and one list of rules — the template's first, the project's after."""

    roots: tuple[str, ...]
    rules: tuple[Tree | Shape | Syntax | Genealogy | Parity, ...]


class Violation(Struct, frozen=True, order=True, kw_only=True):
    """One broken rule at one place: a path relative to the root and its 1-based line."""

    path: str
    line: int
    rule: str
    law: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line} [{self.rule}] law {self.law}: {self.message}"
