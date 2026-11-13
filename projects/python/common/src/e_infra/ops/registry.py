"""ops/registry: static code registry — parse a scope with `ast`, register every symbol by its path, import nothing.

No module runs: facts come from `ast.parse`, the exact grammar of the running interpreter (3.14, PEP 695
included), so discovery has no import side effects and a syntax error fails the scan naming its file. The
space is the model: nodes — packages, modules, files, classes, functions, methods, constants, aliases —
carry a canonical dotted path (`e_infra.ops.registry.CodeRegistry.snapshot`) with a parent pointer; code keys
are dotted inside the `package` prefix, raw files are keyed by their path relative to the root. The registry
is a read-only `Mapping`, `children` answers one level down, and `discover` dispatches on the target's type:
a `Kind` sweeps a category, a name selects the classes that syntactically name it in `bases` (never the MRO
— nothing is imported), a predicate decides freely, `pattern` filters tails. Unlike `ops.file` nothing is
hidden: `_private.py` and `__slots__` are registered and flagged `private`. Only module- and class-level
statements become symbols: a function body is opaque, its signature is the fact. `snapshot` pins the
canonical bytes; `ascan` offloads the walk to a thread."""

import ast
from collections.abc import Iterator, Mapping
from enum import StrEnum, auto
from typing import TYPE_CHECKING

import anyio
import eserde
import msgspec
from msgspec import Struct

from e_infra.infra.errors import RegistryError

if TYPE_CHECKING:
    import re
    from collections.abc import Callable, Sequence
    from pathlib import Path


##### TYPES #####
class Kind(StrEnum):
    PACKAGE = auto()
    MODULE = auto()
    FILE = auto()
    CLASS = auto()
    FUNCTION = auto()
    METHOD = auto()
    CONSTANT = auto()
    ALIAS = auto()


class Symbol(Struct, frozen=True, kw_only=True):
    """One registered fact: what kind it is, where it lives, what it says, and what hangs from it by `parent`."""

    path: str
    kind: Kind
    file: str
    line: int
    parent: str | None = None
    doc: str | None = None
    bases: tuple[str, ...] = ()
    decorators: tuple[str, ...] = ()
    signature: str | None = None
    value: str | None = None
    imports: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        """The final segment: the symbol tail for code, the file name for raw files."""
        return self.path.rpartition("/")[2] if self.kind is Kind.FILE else self.path.rpartition(".")[2]

    @property
    def private(self) -> bool:
        """The underscore law read, never enforced: the registry sees what exists."""
        return self.name.startswith("_")


##### ENGINE #####
class CodeRegistry(Mapping[str, Symbol]):
    """The tool: read a scope tree once, answer any path, kind, base or predicate query over it, import nothing."""

    __slots__ = ("_package", "_root", "_symbols")

    def __init__(self, root: Path, *, package: str | None = None) -> None:
        self._root = root
        self._package = package or root.name
        self._symbols: dict[str, Symbol] | None = None

    ##### PRIVATE #####

    def _common_load(self) -> dict[str, Symbol]:
        match self._symbols:
            case None:
                symbols = self._common_scan()
                self._symbols = dict(sorted(symbols.items()))
            case _:
                pass
        return self._symbols

    def _common_scan(self) -> dict[str, Symbol]:
        match files := [p for p in self._root.rglob("*") if p.is_file() and self._common_visible(p)]:
            case []:
                msg = f"empty scope: no files under {self._root}"
                raise RegistryError(msg)
            case _:
                return {**self._common_space(files), **self._common_code(files)}

    def _common_visible(self, path: Path) -> bool:
        return not any(part.startswith(".") or part == "__pycache__" for part in path.relative_to(self._root).parts)

    def _common_space(self, files: Sequence[Path]) -> dict[str, Symbol]:
        rels = {str(file.relative_to(self._root)): file for file in files}
        heads = {rel.rpartition("/")[0] for rel in rels if rel.endswith(".py")}
        packages = {self._common_dotted(dirpath) for head in heads for dirpath in [head, *self._common_ancestors(head)]}
        return {
            dotted: Symbol(
                path=dotted,
                kind=Kind.PACKAGE,
                file=self._common_dir_of(dotted),
                line=0,
                parent=self._common_parent_of(dotted),
            )
            for dotted in sorted(packages)
        } | {
            rel: Symbol(path=rel, kind=Kind.FILE, file=rel, line=0, parent=self._common_nearest_dir(rel, packages))
            for rel, file in sorted(rels.items())
            if file.suffix != ".py"
        }

    @staticmethod
    def _common_ancestors(head: str) -> list[str]:
        parts = head.split("/") if head else []
        return ["/".join(parts[:i]) for i in range(len(parts) - 1, -1, -1)]

    def _common_dotted(self, dirpath: str) -> str:
        return ".".join([self._package, *dirpath.split("/")]) if dirpath not in ("", ".") else self._package

    def _common_dir_of(self, dotted: str) -> str:
        tail = dotted.removeprefix(self._package).lstrip(".")
        return str(self._root / tail.replace(".", "/")) if tail else str(self._root)

    def _common_nearest_dir(self, rel: str, packages: set[str]) -> str:
        head = rel.rpartition("/")[0]
        parts = head.split("/") if head else []
        return next(
            (
                dotted
                for i in range(len(parts), -1, -1)
                if (dotted := self._common_dotted("/".join(parts[:i]))) in packages
            ),
            self._package,
        )

    def _common_code(self, files: Sequence[Path]) -> dict[str, Symbol]:
        return {path: sym for file in files if file.suffix == ".py" for path, sym in self._common_module(file).items()}

    def _common_module(self, file: Path) -> dict[str, Symbol]:
        rel = str(file.relative_to(self._root))
        is_init = file.name == "__init__.py"
        head = self._common_dotted(rel.rpartition("/")[0])
        modpath = head if is_init else f"{head}.{file.stem}"
        tree = self._common_parse(file, rel)
        doc = self._common_first(ast.get_docstring(tree))
        imports = tuple(self._common_imported(tree, modpath if is_init else modpath.rpartition(".")[0]))
        children = {path: sym for stmt in tree.body for path, sym in self._common_symbol(stmt, modpath, rel).items()}
        match is_init:
            case True:
                return {
                    modpath: Symbol(
                        path=modpath,
                        kind=Kind.PACKAGE,
                        file=rel,
                        line=0,
                        parent=self._common_parent_of(modpath),
                        doc=doc,
                        imports=imports,
                    ),
                    **children,
                }
            case _:
                return {
                    modpath: Symbol(
                        path=modpath,
                        kind=Kind.MODULE,
                        file=rel,
                        line=1,
                        parent=self._common_parent_of(modpath),
                        doc=doc,
                        imports=imports,
                    ),
                    **children,
                }

    def _common_parent_of(self, modpath: str) -> str | None:
        return modpath.rpartition(".")[0] or None

    def _common_parse(self, file: Path, rel: str) -> ast.Module:
        try:
            return ast.parse(file.read_text(), filename=rel)
        except SyntaxError as exc:
            msg = f"syntax error in {rel}: {exc.msg}"
            raise RegistryError(msg) from exc

    def _common_imported(self, tree: ast.Module, pkg: str) -> Iterator[str]:
        return (name for node in ast.walk(tree) for name in self._common_import_names(node, pkg))

    @staticmethod
    def _common_import_names(node: ast.AST, pkg: str) -> tuple[str, ...]:
        match node:
            case ast.Import(names=names):
                return tuple(alias.name for alias in names)
            case ast.ImportFrom(module=module, level=lvl, names=names):
                match module:
                    case None | "":
                        return tuple(f"{CodeRegistry._common_relative(pkg, lvl)}.{alias.name}" for alias in names)
                    case mod:
                        return (mod if lvl == 0 else f"{CodeRegistry._common_relative(pkg, lvl)}.{mod}",)
            case _:
                return ()

    @staticmethod
    def _common_relative(pkg: str, level: int) -> str:
        return ".".join(pkg.split(".")[: len(pkg.split(".")) - level + 1])

    @staticmethod
    def _common_first(doc: str | None) -> str | None:
        return doc.partition("\n")[0] if doc else None

    ##### SYMBOLS #####

    def _common_symbol(self, stmt: ast.stmt, parent: str, rel: str, *, methods: bool = False) -> dict[str, Symbol]:
        match stmt:
            case ast.ClassDef(name=name, body=body, bases=bases, decorator_list=decorators) as node:
                path = f"{parent}.{name}"
                return {
                    path: Symbol(
                        path=path,
                        kind=Kind.CLASS,
                        file=rel,
                        line=node.lineno,
                        parent=parent,
                        doc=self._common_first(ast.get_docstring(node)),
                        bases=tuple(ast.unparse(b) for b in bases),
                        decorators=tuple(ast.unparse(d) for d in decorators),
                    ),
                    **{p: s for inner in body for p, s in self._common_symbol(inner, path, rel, methods=True).items()},
                }
            case (
                ast.FunctionDef(name=name, decorator_list=decorators)
                | ast.AsyncFunctionDef(name=name, decorator_list=decorators)
            ) as node:
                path = f"{parent}.{name}"
                return {
                    path: Symbol(
                        path=path,
                        kind=Kind.METHOD if methods else Kind.FUNCTION,
                        file=rel,
                        line=node.lineno,
                        parent=parent,
                        doc=self._common_first(ast.get_docstring(node)),
                        decorators=tuple(ast.unparse(d) for d in decorators),
                        signature=self._common_signature(node),
                    )
                }
            case ast.Assign(targets=targets, value=value):
                return self._common_constants(parent, rel, stmt, [t for t in targets if isinstance(t, ast.Name)], value)
            case ast.AnnAssign(target=ast.Name() as single, value=value):
                return self._common_constants(parent, rel, stmt, [single], value)
            case ast.TypeAlias(name=ast.Name() as alias, value=value) as node:
                return {
                    f"{parent}.{alias.id}": Symbol(
                        path=f"{parent}.{alias.id}",
                        kind=Kind.ALIAS,
                        file=rel,
                        line=node.lineno,
                        parent=parent,
                        value=ast.unparse(value),
                    )
                }
            case _:
                return {}

    @staticmethod
    def _common_constants(
        parent: str, rel: str, stmt: ast.stmt, named: list[ast.Name], value: ast.expr | None
    ) -> dict[str, Symbol]:
        return {
            f"{parent}.{node.id}": Symbol(
                path=f"{parent}.{node.id}",
                kind=Kind.CONSTANT,
                file=rel,
                line=stmt.lineno,
                parent=parent,
                value=ast.unparse(value) if value is not None else None,
            )
            for node in named
        }

    @staticmethod
    def _common_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        head = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
        returns = f" -> {ast.unparse(node.returns)}" if node.returns else ""
        return f"{head} {node.name}({CodeRegistry._common_params(node.args)}){returns}"

    @staticmethod
    def _common_params(args: ast.arguments) -> str:
        pos = [*args.posonlyargs, *args.args]
        shift = len(pos) - len(args.defaults)
        pieces = [
            CodeRegistry._common_arg(arg, args.defaults[i - shift] if i >= shift else None) for i, arg in enumerate(pos)
        ]
        match args.posonlyargs:
            case [*_] if args.posonlyargs:
                pieces.insert(len(args.posonlyargs), "/")
        match args.vararg:
            case ast.arg() as star:
                pieces.append(f"*{CodeRegistry._common_arg(star)}")
                pieces.extend(
                    CodeRegistry._common_arg(kw, default)
                    for kw, default in zip(args.kwonlyargs, args.kw_defaults, strict=True)
                )
            case _:
                match args.kwonlyargs:
                    case [*_] if args.kwonlyargs:
                        pieces.append("*")
                        pieces.extend(
                            CodeRegistry._common_arg(kw, default)
                            for kw, default in zip(args.kwonlyargs, args.kw_defaults, strict=True)
                        )
        match args.kwarg:
            case ast.arg() as ds:
                pieces.append(f"**{CodeRegistry._common_arg(ds)}")
        return ", ".join(pieces)

    @staticmethod
    def _common_arg(arg: ast.arg, default: ast.expr | None = None) -> str:
        name = arg.arg + (f": {ast.unparse(arg.annotation)}" if arg.annotation else "")
        return name + (f" = {ast.unparse(default)}" if default is not None else "")

    ############################################################

    ##### PUBLIC #####

    def scan(self) -> dict[str, Symbol]:
        """The full catalog, canonically sorted by path — the walk runs on first call and is then frozen."""
        return self._common_load()

    async def ascan(self) -> dict[str, Symbol]:
        """``scan`` off the event loop: the walk and parse are CPU/IO work, not async I/O."""
        return await anyio.to_thread.run_sync(self.scan)

    def discover(
        self, target: Kind | str | Callable[[Symbol], bool], *, pattern: re.Pattern[str] | None = None
    ) -> dict[str, Symbol]:
        """``{path: symbol}`` for whatever ``target`` selects: a category sweep, a syntactic base name, a free predicate."""
        match target:
            case Kind() as kind:
                found = {p: s for p, s in self._common_load().items() if s.kind is kind}
            case str() as base:
                found = {
                    p: s
                    for p, s in self._common_load().items()
                    if s.kind is Kind.CLASS and any(b == base or b.endswith(f".{base}") for b in s.bases)
                }
            case predicate if callable(predicate):
                found = {p: s for p, s in self._common_load().items() if predicate(s)}
            case unknown:
                msg = f"Unsupported discover target: {unknown!r}"
                raise RegistryError(msg)
        match pattern:
            case None:
                return found
            case rx:
                return {p: s for p, s in found.items() if rx.search(s.name)}

    def children(self, path: str) -> dict[str, Symbol]:
        """The one-level subtree: every symbol whose `parent` is exactly this path."""
        return {p: s for p, s in self._common_load().items() if s.parent == path}

    def snapshot(self) -> bytes:
        """Canonical JSON of the whole registry — the golden bytes the tests pin."""
        return eserde.dumps({p: msgspec.to_builtins(s) for p, s in self._common_load().items()}, format="json")

    ############################################################

    ##### MAPPING #####

    def __getitem__(self, path: str) -> Symbol:
        return self._common_load()[path]

    def __iter__(self) -> Iterator[str]:
        return iter(self._common_load())

    def __len__(self) -> int:
        return len(self._common_load())
