"""ops/file: what a file is and what a package holds — deterministic detection, and discovery over a package.

``FileDetector`` names a file from its name and first 64 KiB, Rust and stdlib only, each layer asked in order and the
first that decides named in ``because``: anytomd's ``detect_format`` (magic bytes, then extension) — behind ZIP magic,
``detect_zip_format`` names the office format —, tree-sitter-language-pack's grammar by file name (an extension, or a
known name: ``Dockerfile``, ``Makefile``) then by content (a shebang), ``mimetypes``, and a text sniff (UTF-8, no NUL):
text nobody named is ``html`` when its head is a page, else ``txt``; binary nobody reads has no format. Which reader a
detection goes to is the caller's table, never this module's.

``FileFinder``: agnostic discovery over an installed package — modules, classes, functions.

The sweep is single-level and import-based: files of the package directory, subpackages excluded — unless
``recursive``, which walks every folder below it too (a namespace tree, no ``__init__`` needed) and names a module by
its dotted path under the package; discovery means importing, so a module that fails on import fails the sweep. Symbols are *own* only:
re-exported names never count. A leading underscore is private at file level too: ``_helpers.py`` is
imported never and seen never. ``discover`` dispatches on the target's type: a ``Kind`` sweeps a
category, a base class selects its subclasses (never itself), a module reads that module alone, a
predicate decides freely; ``pattern`` filters the resulting names. ``adiscover``/``asummaries``
offload the import walk to a thread."""

import codecs
import functools
import importlib
import inspect
import mimetypes
import pkgutil
import re
from enum import StrEnum, auto
from pathlib import Path, PurePath
from types import ModuleType
from typing import TYPE_CHECKING, Any, Final

import anyio
import msgspec
from anytomd import detect_format, detect_zip_format
from tree_sitter_language_pack import detect_language, detect_language_from_content

from e_infra.infra.errors import FileError

if TYPE_CHECKING:
    from collections.abc import Callable


##### TYPES #####
class Kind(StrEnum):
    MODULES = auto()
    CLASSES = auto()
    FUNCTIONS = auto()


class FileLayer(StrEnum):
    """The detection layer that decided a file's format."""

    ANYTOMD = auto()
    ZIP = auto()
    PATH = auto()
    CONTENT = auto()
    MIME = auto()
    SNIFF = auto()
    NONE = auto()


class FileDetection(msgspec.Struct, frozen=True, kw_only=True):
    """A file as detection reads it: the format anytomd named (None: no reader has one), its MIME type, the grammar
    tree-sitter names, whether its head is text, and the layer that decided."""

    format: str | None = None
    mime: str | None = None
    language: str | None = None
    is_text: bool = False
    because: FileLayer = FileLayer.NONE


##### DETECTOR #####
### the window detection reads: every magic number and a shebang sit well inside it.
HEAD: Final[int] = 65_536
TEXT: Final[str] = "txt"
HTML: Final[str] = "html"
### a page served with no extension in its address: its head says HTML, comments and white space aside.
MARKUP: Final[re.Pattern[str]] = re.compile(
    r"\A\ufeff?\s*(?:<!--.*?-->\s*)*<(?:!doctype\s+html|html)\b", re.IGNORECASE | re.DOTALL
)


class FileDetector:
    """Names a file from its name and head; holds nothing."""

    __slots__ = ()

    ##### PRIVATE #####

    @staticmethod
    def _classify_text(head: bytes) -> str | None:
        """The head as text when it is: valid UTF-8 (a character cut at the window's edge forgiven), no NUL."""
        try:
            text = codecs.getincrementaldecoder("utf-8")().decode(head)
        except UnicodeDecodeError:
            return None
        return None if "\x00" in text else text

    @staticmethod
    async def _detect_head(path: anyio.Path) -> bytes:
        async with await anyio.open_file(path, "rb") as file:
            return await file.read(HEAD)

    ############################################################

    ##### PUBLIC #####

    @classmethod
    def classify(cls, name: str, head: bytes) -> FileDetection:
        """A file from its name and first bytes alone, no I/O."""
        base = PurePath(name).name
        text = cls._classify_text(head)
        found = detect_format(base, head)
        by_path = detect_language(base)
        by_content = detect_language_from_content(text) if text is not None and by_path is None else None
        detection = FileDetection(
            format=(detect_zip_format(head) or found) if found == "zip" else found,
            mime=mimetypes.guess_file_type(base)[0],
            language=by_path or by_content,
            is_text=text is not None,
        )
        match found, detection.language, detection.is_text:
            case "zip", _, _:
                because = {"because": FileLayer.ZIP}
            case str(), _, _:
                because = {"because": FileLayer.ANYTOMD}
            case None, str(), True:
                because = {"because": FileLayer.PATH if by_path else FileLayer.CONTENT}
            case None, None, True:
                because = {"format": HTML if MARKUP.match(text or "") else TEXT, "because": FileLayer.SNIFF}
            case _:
                because = {"because": FileLayer.MIME if detection.mime else FileLayer.NONE}
        return msgspec.structs.replace(detection, **because)

    async def detect(self, path: anyio.Path | str, head: bytes | None = None) -> FileDetection:
        """A file, reading only its first 64 KiB when no head is handed in. Classification stays on the loop: a few
        Rust calls over at most 64 KiB cost microseconds."""
        source = anyio.Path(path)
        return self.classify(source.name, head if head is not None else await self._detect_head(source))


##### FINDER #####
class FileFinder:
    """Walk a package once; ``discover`` answers whatever ``target`` asks and nothing else."""

    __slots__ = ("_package", "_recursive", "_skip")

    def __init__(self, package: str, *, skip: frozenset[str] = frozenset(), recursive: bool = False) -> None:
        self._package = package
        self._skip = skip
        self._recursive = recursive

    ##### PRIVATE #####

    def _names(self, package: ModuleType) -> list[str]:
        """The module names to sweep: the directory's own files, or every file below it as a dotted path."""
        match self._recursive:
            case True:
                return sorted(
                    {
                        ".".join(path.relative_to(root).with_suffix("").parts)
                        for root in map(Path, package.__path__)
                        for path in root.rglob("*.py")
                        if not any(part.startswith("_") for part in path.relative_to(root).parts)
                    }
                )
            case False:
                return [info.name for info in pkgutil.iter_modules(package.__path__) if not info.ispkg]

    def _modules(self) -> dict[str, ModuleType]:
        package = importlib.import_module(self._package)
        return {
            name: importlib.import_module(f"{self._package}.{name}")
            for name in self._names(package)
            if not name.startswith("_") and name not in self._skip
        }

    @staticmethod
    def _own(mod: ModuleType, predicate: Callable[[object], bool]) -> dict[str, Any]:
        return {
            name: obj
            for name, obj in vars(mod).items()
            if not name.startswith("_") and predicate(obj) and getattr(obj, "__module__", None) == mod.__name__
        }

    def _classes(self, modules: dict[str, ModuleType], of_base: type | None = None) -> dict[str, type]:
        return {
            name: obj
            for module in modules.values()
            for name, obj in self._own(module, inspect.isclass).items()
            ### a base selects its subclasses, never itself — even when it lives in the swept package.
            if of_base is None or (issubclass(obj, of_base) and obj is not of_base)
        }

    def _functions(self, modules: dict[str, ModuleType]) -> dict[str, Any]:
        return {name: obj for module in modules.values() for name, obj in self._own(module, inspect.isfunction).items()}

    def _select(self, target: Any, modules: dict[str, ModuleType], pattern: re.Pattern[str] | None) -> dict[str, Any]:
        match target:
            case Kind.MODULES:
                found: dict[str, Any] = modules
            case Kind.CLASSES:
                found = self._classes(modules)
            case Kind.FUNCTIONS:
                found = self._functions(modules)
            case ModuleType() as module:
                found = {**self._own(module, inspect.isclass), **self._own(module, inspect.isfunction)}
            case type() as base:
                found = self._classes(modules, base)
            case predicate if callable(predicate):
                found = {
                    k: v for k, v in {**self._classes(modules), **self._functions(modules)}.items() if predicate(v)
                }
            case unknown:
                msg = f"Unsupported discover target: {unknown!r}"
                raise FileError(msg)
        match pattern:
            case None:
                return found
            case rx:
                return {name: obj for name, obj in found.items() if rx.search(name)}

    ############################################################

    ##### PUBLIC #####

    @staticmethod
    def summary(module: ModuleType) -> str:
        """The module's top description — its first docstring line, ``<path>: <summary>.`` by contract."""
        return lines[0] if (lines := (inspect.getdoc(module) or "").splitlines()) else ""

    def discover(
        self, target: Kind | type | ModuleType | Callable[[Any], bool], *, pattern: re.Pattern[str] | None = None
    ) -> dict[str, Any]:
        """Return ``{name: object}`` for whatever ``target`` selects across the package's modules."""
        return self._select(target, self._modules(), pattern)

    def summaries(self) -> dict[str, str]:
        """One-line description per module of the package — what a display surface renders."""
        return {name: self.summary(mod) for name, mod in self._modules().items()}

    async def asummaries(self) -> dict[str, str]:
        """``summaries`` off the event loop, for the display surfaces that live inside a running app."""
        return await anyio.to_thread.run_sync(self.summaries)

    async def adiscover(
        self, target: Kind | type | ModuleType | Callable[[Any], bool], *, pattern: re.Pattern[str] | None = None
    ) -> dict[str, Any]:
        """``discover`` off the event loop: the import walk is CPU/IO work, not async I/O."""
        return await anyio.to_thread.run_sync(functools.partial(self.discover, target, pattern=pattern))
