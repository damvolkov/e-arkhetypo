"""ops/file: agnostic discovery over an installed package — modules, classes, functions.

The sweep is single-level and import-based: files of the package directory, subpackages excluded;
discovery means importing, so a module that fails on import fails the sweep. Symbols are *own* only:
re-exported names never count. A leading underscore is private at file level too: ``_helpers.py`` is
imported never and seen never. ``discover`` dispatches on the target's type: a ``Kind`` sweeps a
category, a base class selects its subclasses (never itself), a module reads that module alone, a
predicate decides freely; ``pattern`` filters the resulting names. ``adiscover``/``asummaries``
offload the import walk to a thread."""

import functools
import importlib
import inspect
import pkgutil
from enum import StrEnum, auto
from types import ModuleType
from typing import TYPE_CHECKING, Any

import anyio

if TYPE_CHECKING:
    import re
    from collections.abc import Callable


##### TYPES #####
class FileError(TypeError):
    """A discover target this tool refuses to interpret."""


class Kind(StrEnum):
    MODULES = auto()
    CLASSES = auto()
    FUNCTIONS = auto()


##### FINDER #####
class FileFinder:
    """Walk a package once; ``discover`` answers whatever ``target`` asks and nothing else."""

    __slots__ = ("_package", "_skip")

    def __init__(self, package: str, *, skip: frozenset[str] = frozenset()) -> None:
        self._package = package
        self._skip = skip

    ##### PRIVATE #####

    def _modules(self) -> dict[str, ModuleType]:
        package = importlib.import_module(self._package)
        return {
            info.name: importlib.import_module(f"{self._package}.{info.name}")
            for info in pkgutil.iter_modules(package.__path__)
            if not info.ispkg and not info.name.startswith("_") and info.name not in self._skip
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
