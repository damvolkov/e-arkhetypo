"""logic.discover: find, decode, judge and resolve a pipeline's specs and the runners they plug — lazily, by section.

The tree it reads:

    specs/<pipeline>/<section>/<PFX>-<words>.yaml        a pipeline's specs, one folder per section
    specs/wiki/<term>.md · specs/<pipeline>/wiki/        glossaries (a pipeline's own page wins)
    runners/owned/<pipeline>/<section>/<name>.py         runners owned by one pipeline's section
    runners/agnostic/<capability>/<name>.py              tools any spec of any pipeline may plug

`SpecDiscover` serves one pipeline. Nothing happens at construction; `sections()` lists folders only;
`catalog(section)` builds a section the first time it is asked, in a worker thread, and keeps it:

1. every spec file is read, refused if it uses a merge key, decoded into the section's tagged union;
2. every runner the specs plug is resolved and read by AST — functions, signatures, docstrings;
3. the section's laws (`logic.rules`) judge the whole draft, every breach collected;
4. only then the plugged modules are executed — once, never an unplugged one — to validate each slot's
   `args` against the runner's `Args`; a module that raises while loading is a breach, not a crash;
5. the specs are paired with their runners and validated args into a `Catalog` — or every breach is
   raised at once as a `CatalogError`.

`SystemDiscover` serves the whole system: every pipeline's audit plus the laws only the whole can tell —
specs or owned runners of a pipeline that does not exist, specs of a section its pipeline never mounts,
tools nobody plugs (a warning). `check` returns a `Report`: the static check DARTSOPS runs."""

import asyncio
import importlib.util
import operator
import threading
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from functools import reduce
from importlib.machinery import ModuleSpec, SourceFileLoader
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, cast

import anyio
import eserde
import msgspec

from e_graph.logic.errors import AuditError, CatalogError, Rule, RuleError, Severity
from e_graph.logic.models import (
    ROLES,
    Breach,
    Catalog,
    DeterministicSpec,
    Draft,
    Function,
    Module,
    Report,
    Runner,
    Scope,
    SemanticSpec,
    Slot,
    Spec,
    SpecNode,
)
from e_graph.logic.rules import (
    RUNNER_SUFFIX,
    SECTIONS,
    SPEC_SUFFIX,
    WIKI,
    WORD,
    judge_section,
    rule_merge,
    rule_tree,
)
from e_graph.models.section import ORDER, Section
from infra.struct import CheckedStruct
from ops.registry import CodeRegistry, Kind

if TYPE_CHECKING:
    from types import ModuleType

type Hookable = Callable[..., Awaitable[Any]]

PACKAGE: Final[Path] = Path(__file__).resolve().parents[1]
SPECS: Final[Path] = PACKAGE / "specs"
RUNNERS: Final[Path] = PACKAGE / "runners"
KINDS: Final[tuple[type[Spec], ...]] = (DeterministicSpec, SemanticSpec)
WALK: Final[tuple[Section, ...]] = (*ORDER, Section.CUSTOM)
SCOPES: Final[frozenset[str]] = frozenset(Scope)
FOLDERS: Final[frozenset[str]] = SECTIONS | {WIKI}


class SpecDiscover:
    """One pipeline's specs and the runners they plug, discovered section by section as needed, then kept."""

    __slots__ = ("_catalogs", "_guard", "_kinds", "_locks", "_modules", "_pipeline", "_runners", "_specs")

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
        self._locks: dict[Section, anyio.Lock] = {}
        self._modules: dict[str, ModuleType] = {}
        self._guard = threading.Lock()

    ##### PRIVATE #####

    def _catalog_build(self, section: Section) -> Catalog:
        """The section judged whole: a catalog of resolved specs, or every breach at once."""
        specs, failures = self._catalog_specs(section)
        pages = self._catalog_wiki()
        draft = Draft(
            pipeline=self._pipeline,
            section=section,
            specs=specs,
            modules=self._catalog_modules(section, specs),
            owned=self._catalog_owned(section),
            wiki=frozenset(pages),
            broken=frozenset(Path(failure.subject).stem for failure in failures),
        )
        ### args need the plugged modules executed: only once every law about them holds.
        match [*failures, *judge_section(draft)]:
            case []:
                args, refused = self._catalog_args(draft)
            case breaches:
                args, refused = {}, breaches
        match refused:
            case []:
                terms = {term for spec in draft.specs.values() for term in spec.wiki}
                wiki = {term: pages[term].read_text(encoding="utf-8") for term in sorted(terms)}
                nodes = self._catalog_nodes(draft, args)
                return Catalog(pipeline=self._pipeline, section=section, nodes=nodes, wiki=wiki)
            case _:
                msg = f"{self._pipeline}/{section}: {len(refused)} broken laws"
                raise CatalogError(msg, refused)

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

    def _catalog_file(self, section: Section, ref: str) -> Path:
        """Where a reference points: an owned runner in this pipeline's section, an agnostic one in its capability."""
        scope, _, rest = ref.partition("/")
        match Scope(scope):
            case Scope.OWNED:
                return self._runners / Scope.OWNED / self._pipeline / section / f"{rest}{RUNNER_SUFFIX}"
            case _:
                return self._runners / Scope.AGNOSTIC / f"{rest}{RUNNER_SUFFIX}"

    def _catalog_modules(self, section: Section, specs: Mapping[str, Spec[str]]) -> dict[str, Module]:
        """Every runner the specs plug, resolved and read by AST: its top-level functions, never executed."""
        files = {
            ref: self._catalog_file(section, ref)
            for ref in sorted({r for s in specs.values() for r in s.plugs.values()})
        }
        found = {file for file in files.values() if file.is_file()}
        owners = {f"{file.parent.name}.{file.stem}": file for file in found}
        symbols = [
            symbol
            for folder in sorted({file.parent for file in found})
            for symbol in CodeRegistry(folder, package=folder.name).scan().values()
            if symbol.kind is Kind.FUNCTION and symbol.parent in owners
        ]
        return {
            ref: Module(
                ref=ref,
                file=str(file),
                exists=file in found,
                functions=tuple(
                    Function(name=symbol.name, signature=symbol.signature, doc=symbol.doc)
                    for symbol in symbols
                    if owners[cast("str", symbol.parent)] == file
                ),
            )
            for ref, file in files.items()
        }

    def _catalog_owned(self, section: Section) -> frozenset[str]:
        """Every owned runner module of the pipeline's section, by name."""
        folder = self._runners / Scope.OWNED / self._pipeline / section
        return frozenset(file.stem for file in folder.glob(f"*{RUNNER_SUFFIX}") if WORD.fullmatch(file.stem))

    def _catalog_wiki(self) -> dict[str, Path]:
        """Every wiki page in reach, by term: the shared ones, then the pipeline's own, which win."""
        folders = (self._specs / WIKI, self._specs / self._pipeline / WIKI)
        return {file.stem: file for folder in folders if folder.is_dir() for file in sorted(folder.glob("*.md"))}

    def _catalog_args(self, draft: Draft) -> tuple[dict[tuple[str, Slot], Any], list[RuleError]]:
        """Each plugged slot's `args` decoded into its runner's `Args` — `{}` for a runner that declares none."""
        outcomes = {
            (stem, slot): self._catalog_arg(spec, slot, draft.modules[ref].file)
            for stem, spec in draft.specs.items()
            for slot, ref in spec.plugs.items()
        }
        args = {key: value for key, value in outcomes.items() if not isinstance(value, RuleError)}
        return args, [value for value in outcomes.values() if isinstance(value, RuleError)]

    def _catalog_arg(self, spec: Spec[str], slot: Slot, file: str) -> Any:
        """One slot's args validated against its runner's `Args`, or the breach that says why not."""
        given, ref, subject = spec.args.get(slot, {}), spec.plugs[slot], f"{spec.name}.{slot}"
        try:
            module = self._load_module(file)
        except Exception as error:  # noqa: BLE001 — a runner that cannot load is a breach to report, never a crash
            return RuleError(Rule.RUNNER, subject, f"{ref} does not load: {type(error).__name__}: {error}")
        match getattr(module, "Args", None):
            case None if given:
                return RuleError(Rule.ARGS, subject, f"{ref} declares no Args, given {sorted(given)}")
            case None:
                return {}
            case declared:
                try:
                    return CheckedStruct.convert(given, declared)
                except msgspec.ValidationError as error:
                    return RuleError(Rule.ARGS, subject, f"{ref}: {error}")

    def _catalog_nodes(self, draft: Draft, args: Mapping[tuple[str, Slot], Any]) -> dict[str, SpecNode]:
        """Each spec with the runners it plugs, resolved, and each slot's validated args."""
        return {
            name: SpecNode(
                spec=spec,
                file=str(self._specs / self._pipeline / draft.section / f"{name}{SPEC_SUFFIX}"),
                runners={
                    slot: Runner(
                        ref=ref,
                        role=ROLES[slot],
                        file=draft.modules[ref].file,
                        doc=draft.modules[ref].functions[0].doc,
                    )
                    for slot, ref in spec.plugs.items()
                },
                args={slot: args[name, slot] for slot in spec.plugs},
            )
            for name, spec in draft.specs.items()
        }

    def _load_module(self, file: str) -> ModuleType:
        """A runner module executed from its file — never through the import path — once per discovery."""
        with self._guard:
            match self._modules.get(file):
                case None:
                    parts = Path(file).relative_to(self._runners).with_suffix("").parts
                    match importlib.util.spec_from_file_location(".".join(("darts", *parts)), file):
                        case ModuleSpec(loader=SourceFileLoader() as loader) as found:
                            ### kept only once executed whole: a module that raised is never served half-built.
                            module = importlib.util.module_from_spec(found)
                            loader.exec_module(module)
                            self._modules[file] = module
                            return module
                        case _:
                            msg = f"{file} is no Python source: its runner cannot load"
                            raise ImportError(msg)
                case module:
                    return module

    ############################################################

    ##### PUBLIC #####

    @property
    def pipeline(self) -> str:
        return self._pipeline

    @property
    def built(self) -> tuple[Catalog, ...]:
        """The sections built so far and judged coherent, in walking order."""
        return tuple(self._catalogs[section] for section in WALK if section in self._catalogs)

    def sections(self) -> tuple[Section, ...]:
        """The sections this pipeline has specs for, in walking order — folder names only."""
        root = self._specs / self._pipeline
        return tuple(section for section in WALK if (root / section).is_dir())

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
        """Every section built at once, plus the pipeline's tree laws: all catalogs, or one group of every breach."""
        outcomes = await asyncio.gather(*(self.catalog(section) for section in self.sections()), return_exceptions=True)
        tree = [
            *rule_tree(self._specs / self._pipeline, SPEC_SUFFIX, FOLDERS.__contains__, skip=frozenset({WIKI})),
            *rule_tree(self._runners / Scope.OWNED / self._pipeline, RUNNER_SUFFIX, SECTIONS.__contains__),
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
        """The runner's function: its module was executed when its args were validated, or is now, once."""
        module = await anyio.to_thread.run_sync(self._load_module, runner.file)
        return cast("Hookable", getattr(module, runner.role))


class SystemDiscover:
    """Every pipeline at once, plus the laws only the whole system can tell: the static check DARTSOPS runs."""

    __slots__ = ("_kinds", "_mounts", "_runners", "_specs")

    def __init__(
        self,
        mounts: Mapping[str, frozenset[Section]],
        *,
        specs: Path = SPECS,
        runners: Path = RUNNERS,
        kinds: tuple[type[Spec], ...] = KINDS,
    ) -> None:
        self._mounts = mounts
        self._specs, self._runners, self._kinds = specs, runners, kinds

    ##### PRIVATE #####

    @staticmethod
    def _common_folders(root: Path, *, skip: frozenset[str] = frozenset()) -> list[Path]:
        """The folders under a root, sorted; none if the root is absent."""
        return sorted(e for e in root.iterdir() if e.is_dir() and e.name not in skip) if root.is_dir() else []

    def _check_system(self) -> list[RuleError]:
        """The whole tree's laws: known pipelines only, mounted sections only, scoped and one-word runner folders."""
        specs = self._common_folders(self._specs, skip=frozenset({WIKI}))
        owners = self._common_folders(self._runners / Scope.OWNED)
        return [
            *(
                RuleError(Rule.PIPELINE, str(entry), f"{kind} of no pipeline: it was removed or renamed")
                for kind, entries in (("specs", specs), ("runners", owners))
                for entry in entries
                if entry.name not in self._mounts
            ),
            *(
                RuleError(
                    Rule.UNMOUNTED, str(folder), f"{entry.name} mounts no {folder.name} node: these specs never run"
                )
                for entry in specs
                if entry.name in self._mounts
                for folder in self._common_folders(entry)
                if folder.name in SECTIONS and Section(folder.name) not in self._mounts[entry.name]
            ),
            *rule_tree(self._runners, RUNNER_SUFFIX, SCOPES.__contains__, skip=SCOPES),
            *rule_tree(
                self._runners / Scope.OWNED, RUNNER_SUFFIX, WORD.fullmatch, skip=frozenset(e.name for e in owners)
            ),
            *rule_tree(self._runners / Scope.AGNOSTIC, RUNNER_SUFFIX, WORD.fullmatch),
        ]

    def _check_idle(self, catalogs: tuple[Catalog, ...]) -> list[RuleError]:
        """Agnostic tools no spec of any pipeline plugs: a warning — a toolbox may wait for its use."""
        plugged = {
            runner.ref for catalog in catalogs for node in catalog.nodes.values() for runner in node.runners.values()
        }
        root = self._runners / Scope.AGNOSTIC
        tools = sorted(f"{Scope.AGNOSTIC}/{file.parent.name}/{file.stem}" for file in root.glob(f"*/*{RUNNER_SUFFIX}"))
        return [
            RuleError(Rule.IDLE, ref, "no spec plugs this tool", Severity.WARNING)
            for ref in tools
            if ref not in plugged
        ]

    @staticmethod
    def _check_breaches(outcome: tuple[Catalog, ...] | BaseException) -> list[RuleError]:
        """Every breach one pipeline's audit raised, flattened; anything but an audit failure propagates."""
        match outcome:
            case tuple():
                return []
            case AuditError():
                return [breach for group in outcome.catalogs for breach in group.breaches]
            case _:
                raise outcome

    ############################################################

    ##### PUBLIC #####

    async def check(self, only: frozenset[str] = frozenset()) -> Report:
        """Every pipeline audited (or `only` those), plus the system's own laws: one report of every breach."""
        pipelines = tuple(sorted(only or self._mounts))
        discovers = [SpecDiscover(p, specs=self._specs, runners=self._runners, kinds=self._kinds) for p in pipelines]
        outcomes = await asyncio.gather(*(discover.audit() for discover in discovers), return_exceptions=True)
        ### a broken section never hides the sound ones: every catalog built counts, whatever its pipeline's verdict.
        catalogs = tuple(catalog for discover in discovers for catalog in discover.built)
        audited = [breach for outcome in outcomes for breach in self._check_breaches(outcome)]
        unknown = [
            RuleError(Rule.PIPELINE, name, "no graph mounts this pipeline") for name in sorted(only - set(self._mounts))
        ]
        ### a tool idle in the pipelines checked may be plugged by the others: idleness is judged on the whole only.
        idle = [] if only else self._check_idle(catalogs)
        breaches = [*unknown, *self._check_system(), *audited, *idle]
        return Report(
            pipelines=pipelines,
            sections=len(catalogs),
            specs=sum(len(catalog.nodes) for catalog in catalogs),
            breaches=tuple(
                Breach(rule=error.rule, subject=error.subject, detail=error.detail, severity=error.severity)
                for error in breaches
            ),
        )
