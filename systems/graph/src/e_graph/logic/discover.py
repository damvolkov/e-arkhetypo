"""logic.discover: find, decode, judge and pair a pipeline's specs and runners — lazily, one section at a time.

Nothing happens at construction. `sections()` is the cheap index: which section folders a pipeline has,
in `ORDER`, `CUSTOM` last — directory names only, no file read. A section is built the first time it is
asked for (`catalog`), in a worker thread, and cached:

1. every `specs/<pipeline>/<section>/*.yaml` is read, refused if it uses a merge key, and decoded by
   e-serde straight into the section's tagged union — each kind parametrized by the section's name
   type, so msgspec validates every name, dependency and fallback against the section's prefix;
2. every `runners/<pipeline>/<section>/*.py` is read by AST (`ops.registry.CodeRegistry`), never
   imported: its top-level functions, their signatures and docstrings;
3. the section's laws (`logic.rules`) judge the whole draft; every breach is collected and raised
   together as a `CatalogError` — or the specs are paired with their hooks into a `Catalog`.

`walk()` yields the catalogs in order as they are consumed, so a run builds only the sections it
reaches. `audit()` builds them all, plus the pipeline's tree laws, and reports every breach of every
section at once — the CI and boot gate that leaves nothing dangling. `load` imports one runner's hook,
on first use only: the one dynamic import the house allows."""

import asyncio
import importlib.util
import operator
from collections.abc import AsyncIterator, Awaitable, Callable
from functools import reduce
from importlib.machinery import ModuleSpec, SourceFileLoader
from pathlib import Path
from typing import Any, Final, cast

import anyio
import eserde

from core.struct import CheckedStruct
from e_graph.logic.errors import AuditError, CatalogError, Rule, RuleError
from e_graph.logic.models import (
    Catalog,
    DeterministicSpec,
    Draft,
    Function,
    Hook,
    Runner,
    SemanticSpec,
    Spec,
    SpecNode,
)
from e_graph.logic.rules import RUNNER_SUFFIX, SPEC_SUFFIX, WIKI, judge_section, rule_merge, rule_tree
from e_graph.models.section import ORDER, Section
from ops.registry import CodeRegistry, Kind

type Hookable = Callable[..., Awaitable[Any]]

PACKAGE: Final[Path] = Path(__file__).resolve().parents[1]
SPECS: Final[Path] = PACKAGE / "specs"
RUNNERS: Final[Path] = PACKAGE / "runners"
KINDS: Final[tuple[type[Spec], ...]] = (DeterministicSpec, SemanticSpec)
WALK: Final[tuple[Section, ...]] = (*ORDER, Section.CUSTOM)


class SpecDiscover:
    """One pipeline's specs and runners, discovered section by section as they are needed, then kept."""

    __slots__ = ("_catalogs", "_kinds", "_loaded", "_locks", "_pipeline", "_runners", "_specs")

    def __init__(
        self,
        pipeline: str,
        *,
        specs: Path = SPECS,
        runners: Path = RUNNERS,
        kinds: tuple[type[Spec], ...] = KINDS,
    ) -> None:
        self._pipeline = pipeline
        self._specs, self._runners = specs, runners
        self._kinds = kinds
        self._catalogs: dict[Section, Catalog] = {}
        self._locks: dict[str, anyio.Lock] = {}
        self._loaded: dict[str, Hookable] = {}

    ##### PRIVATE #####

    def _catalog_build(self, section: Section) -> Catalog:
        """The section judged whole: a coherent catalog, or every breach at once."""
        specs, failures = self._catalog_specs(section)
        draft = Draft(
            pipeline=self._pipeline,
            section=section,
            specs=specs,
            functions=self._catalog_functions(section),
            wiki=self._catalog_wiki(),
            broken=frozenset(Path(failure.subject).stem for failure in failures),
        )
        match [*failures, *judge_section(draft)]:
            case []:
                return Catalog(pipeline=self._pipeline, section=section, nodes=self._catalog_nodes(draft))
            case breaches:
                msg = f"{self._pipeline}/{section}: {len(breaches)} broken laws"
                raise CatalogError(msg, breaches)

    def _catalog_specs(self, section: Section) -> tuple[dict[str, Spec[str]], list[RuleError]]:
        """Every spec file of the section decoded into its union, or the reasons it could not be."""
        union = self._catalog_union(section)
        files = sorted((self._specs / self._pipeline / section).glob(f"*{SPEC_SUFFIX}"))
        decoded = [(file, self._catalog_decode(file, union)) for file in files]
        specs = {file.stem: spec for file, spec in decoded if isinstance(spec, Spec)}
        failures = [error for _, outcome in decoded if isinstance(outcome, list) for error in outcome]
        return specs, failures

    def _catalog_union(self, section: Section) -> Any:
        """The tagged union every spec of the section decodes into, each kind bound to the section's name type."""
        name = Spec.named(section)
        return reduce(operator.or_, (cast("Any", kind)[name] for kind in self._kinds))

    @staticmethod
    def _catalog_decode(file: Path, union: Any) -> Spec[str] | list[RuleError]:
        """One spec file, source laws first, then decoded and validated by msgspec in one pass."""
        text = file.read_text(encoding="utf-8")
        match list(rule_merge(file, text)):
            case []:
                try:
                    with CheckedStruct.trusted():
                        decoded = eserde.loads(text, format="yaml", type=union, dec_hook=CheckedStruct.dec_hook)
                    return cast("Spec[str]", decoded)
                except eserde.CodecError as error:
                    return [RuleError(Rule.DECODE, str(file), str(error))]
            case breaches:
                return breaches

    def _catalog_functions(self, section: Section) -> dict[str, tuple[Function, ...]]:
        """Every runner module's top-level functions, by module name, read from the source alone."""
        root = self._runners / self._pipeline / section
        match sorted(root.glob(f"*{RUNNER_SUFFIX}")) if root.is_dir() else []:
            case []:
                return {}
            case files:
                symbols = CodeRegistry(root, package=section.value).scan()
                modules = {f"{section}.{file.stem}": file for file in files}
                functions = [
                    (modules[symbol.parent], symbol)
                    for symbol in symbols.values()
                    if symbol.kind is Kind.FUNCTION and symbol.parent in modules
                ]
                return {
                    file.stem: tuple(
                        Function(name=symbol.name, signature=symbol.signature, doc=symbol.doc, file=str(file))
                        for owner, symbol in functions
                        if owner == file
                    )
                    for file in files
                }

    def _catalog_wiki(self) -> frozenset[str]:
        """Every wiki term in reach: the pipeline's own, then the shared ones."""
        folders = (self._specs / self._pipeline / WIKI, self._specs / WIKI)
        return frozenset(file.stem for folder in folders if folder.is_dir() for file in folder.glob("*.md"))

    def _catalog_nodes(self, draft: Draft) -> dict[str, SpecNode]:
        """Each spec paired with the hooks its runner module defines — the rules already proved they fit."""
        root = self._runners / self._pipeline / draft.section
        return {
            name: SpecNode(
                spec=spec,
                file=str(self._specs / self._pipeline / draft.section / f"{name}{SPEC_SUFFIX}"),
                hooks={
                    Hook(function.name): Runner(
                        spec=name, hook=Hook(function.name), file=str(root / f"{name}{RUNNER_SUFFIX}"), doc=function.doc
                    )
                    for function in draft.functions.get(name, ())
                },
            )
            for name, spec in draft.specs.items()
        }

    def _load_hook(self, runner: Runner) -> Hookable:
        """Import the runner's module from its file and take the hook — never through the import path."""
        name = f"e_graph.runners.{self._pipeline}.{Path(runner.file).parent.name}.{runner.spec}"
        match importlib.util.spec_from_file_location(name, runner.file):
            case ModuleSpec(loader=SourceFileLoader() as loader) as found:
                module = importlib.util.module_from_spec(found)
                loader.exec_module(module)
                return cast("Hookable", getattr(module, runner.hook))
            case _:
                msg = f"{runner.file} is no Python source: runner {runner.name} cannot load"
                raise ImportError(msg)

    ############################################################

    ##### PUBLIC #####

    @property
    def pipeline(self) -> str:
        return self._pipeline

    def sections(self) -> tuple[Section, ...]:
        """The sections this pipeline has specs or runners for, in walking order — folder names only."""
        roots = (self._specs / self._pipeline, self._runners / self._pipeline)
        return tuple(section for section in WALK if any((root / section).is_dir() for root in roots))

    async def catalog(self, section: Section) -> Catalog:
        """The section's catalog: built on first request, off the loop, then served from memory."""
        async with self._locks.setdefault(section, anyio.Lock()):
            match self._catalogs.get(section):
                case None:
                    built = self._catalogs[section] = await anyio.to_thread.run_sync(self._catalog_build, section)
                    return built
                case cached:
                    return cached

    def walk(self) -> AsyncIterator[Catalog]:
        """Every section's catalog in order, each built only when the consumer reaches it."""
        return (await self.catalog(section) for section in self.sections())

    async def audit(self) -> tuple[Catalog, ...]:
        """Every section built at once, plus the tree laws: all catalogs, or one group holding every breach."""
        outcomes = await asyncio.gather(*(self.catalog(section) for section in self.sections()), return_exceptions=True)
        tree = [
            *rule_tree(self._specs / self._pipeline, SPEC_SUFFIX),
            *rule_tree(self._runners / self._pipeline, RUNNER_SUFFIX),
        ]
        failed = [
            *([CatalogError(f"{self._pipeline}: {len(tree)} broken tree laws", tree)] if tree else []),
            *(outcome for outcome in outcomes if isinstance(outcome, CatalogError)),
        ]
        unexpected = [
            outcome
            for outcome in outcomes
            if isinstance(outcome, BaseException) and not isinstance(outcome, CatalogError)
        ]
        match (unexpected, failed):
            case ([error, *_], _):
                raise error
            case ([], []):
                return tuple(cast("list[Catalog]", outcomes))
            case _:
                msg = f"{self._pipeline}: {len(failed)} incoherent parts"
                raise AuditError(msg, failed)

    async def load(self, runner: Runner) -> Hookable:
        """The runner's hook function, imported on first use and kept — once, however many ask at the same time."""
        async with self._locks.setdefault(runner.name, anyio.Lock()):
            match self._loaded.get(runner.name):
                case None:
                    hook = self._loaded[runner.name] = await anyio.to_thread.run_sync(self._load_hook, runner)
                    return hook
                case loaded:
                    return loaded
