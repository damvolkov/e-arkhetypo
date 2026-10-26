"""tests/support/crafter: craft a coherent DARTS pipeline on disk — then break it, one law at a time.

`SpecCrafter` builds specs the way production code would: in Python, as `CheckedStruct`s, so every
crafted spec is validated at birth. pytest-resources (`resources.make`, polyfactory) fills every
free field at random — description, instructions, tier, bound, version — while the crafter pins
the structure it must control: names, the dependency DAG, fallbacks, wiki terms, schemas, timeouts and
the runners each spec plugs. Each spec is written as YAML (e-serde), each runner it plugs as an owned
module holding its one role function, each wiki term as markdown: a tree `SpecDiscover` reads exactly as
it would read a real pipeline.

A crafted spec `EXT-total-3` plugs owned modules named after it: `total3` (its `run`), `total3check`,
`total3pre`, `total3post` — whichever slots it fills. The `Blueprint` remembers what was crafted — the
specs and the runners each plugs, by slot — so a test compares the catalog against intent, and picks
the spec a breach should hit."""

import random
from dataclasses import dataclass, field
from datetime import timedelta
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

import eserde
import msgspec

from e_graph.logic.discover import SpecDiscover
from e_graph.logic.models import ROLES, SIGNATURES, DeterministicSpec, JsonSchema, Role, SemanticSpec, Slot, Spec
from e_graph.models.section import PREFIXES, Section
from infra.struct import CheckedStruct

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from pathlib import Path

    from pytest_resources import Resources

### the field pool crafted output schemas draw from: name → JSON Schema of the property.
PROPERTIES: Final[Mapping[str, dict[str, Any]]] = {
    "total": {"type": "number"},
    "currency": {"type": "string", "enum": ["EUR", "USD"]},
    "lines": {"type": "array", "items": {"type": "object", "properties": {"sku": {"type": "string"}}}},
    "date": {"type": "string"},
    "pages": {"type": "integer", "minimum": 0},
}
BODIES: Final[Mapping[Role, str]] = MappingProxyType(
    {
        Role.RUN: "return {}",
        Role.CHECK: "return True",
        Role.PRE: 'return ""',
        Role.POST: "return output",
    }
)
### the module a spec's slot is plugged with: `<stem><suffix>`, `total3` · `total3check` · `total3pre` · `total3post`.
SUFFIXES: Final[Mapping[Slot, str]] = MappingProxyType(
    {Slot.RUNNER: "", Slot.CHECK: "check", Slot.PRE: "pre", Slot.POST: "post"}
)
HEADER: Final[str] = (
    "from typing import Any\n\nfrom e_graph.instrument.state import RunState\nfrom e_graph.logic.models import Call\n"
)
WORDS: Final[tuple[str, ...]] = ("total", "net", "tax", "line", "page", "party", "date", "fee", "sum", "ratio")


def stem(name: str) -> str:
    """The one-word module stem of a spec: `EXT-net-income-3` → `netincome3`."""
    return "".join(name.split("-")[1:])


def plug(name: str, slot: Slot) -> str:
    """The owned reference a spec's slot is plugged with."""
    return f"owned/{stem(name)}{SUFFIXES[slot]}"


@dataclass(slots=True)
class Blueprint:
    """What was crafted for one section: the specs by name, each with the runners it plugs by slot."""

    section: Section
    specs: dict[str, Spec[str]] = field(default_factory=dict)

    @property
    def deterministic(self) -> list[str]:
        return [name for name, spec in self.specs.items() if isinstance(spec, DeterministicSpec)]

    @property
    def semantic(self) -> list[str]:
        return [name for name, spec in self.specs.items() if isinstance(spec, SemanticSpec)]

    @property
    def plugs(self) -> dict[str, dict[Slot, str]]:
        """Spec → the runners it plugs, by slot."""
        return {name: spec.plugs for name, spec in self.specs.items()}

    @property
    def fallbacks(self) -> dict[str, str]:
        """Parent → the spec it falls back to."""
        return {name: spec.fallback for name, spec in self.specs.items() if spec.fallback is not None}

    @property
    def edges(self) -> set[tuple[str, str]]:
        """(dependency, dependent) pairs — the section's DAG as crafted."""
        return {(dependency, name) for name, spec in self.specs.items() for dependency in spec.depends}


class SpecCrafter:
    """Writes crafted pipelines under a root and hands out the discovery that reads them."""

    __slots__ = ("_resources", "_rng", "_seed", "pipeline", "runners", "specs")

    def __init__(self, resources: Resources, root: Path, *, seed: int, pipeline: str = "doc") -> None:
        self._resources, self._seed, self._rng = resources, seed, random.Random(seed)
        self.pipeline = pipeline
        self.specs, self.runners = root / "specs", root / "runners"

    ##### PRIVATE #####

    def _craft_names(self, section: Section, n: int) -> list[str]:
        """`n` distinct spec names in the section's grammar: `<PREFIX>-<word>-<index>`."""
        return [f"{PREFIXES[section]}-{self._rng.choice(WORDS)}-{index}" for index in range(n)]

    def _craft_output(self) -> JsonSchema:
        picked = self._rng.sample(sorted(PROPERTIES), k=self._rng.randint(1, len(PROPERTIES)))
        return JsonSchema({"type": "object", "properties": {name: PROPERTIES[name] for name in picked}})

    def _craft_spec(self, kind: type[Spec[str]], name: str, **pins: Any) -> Spec[str]:
        """A random spec of `kind`, structure pinned — built in code, so validated at birth by `CheckedStruct`."""
        timeout = timedelta(seconds=self._rng.randint(1, 600)) if self._rng.random() < 0.5 else None
        extra = {"examples": ({},) if self._rng.random() < 0.3 else ()} if kind is SemanticSpec else {}
        seed = self._rng.randrange(2**32)
        return self._resources.make(kind, seed=seed, name=name, timeout=timeout, args={}, **extra, **pins)

    def _craft_kind(self, semantic: float) -> type[Spec[str]]:
        return SemanticSpec if self._rng.random() < semantic else DeterministicSpec

    def _craft_plugs(self, kind: type[Spec[str]], name: str) -> dict[str, str | None]:
        """The runners a spec plugs: a deterministic one its `runner` always, every optional slot at even odds."""
        optional = {slot.value: plug(name, slot) if self._rng.random() < 0.5 else None for slot in kind.SLOTS}
        return optional | ({Slot.RUNNER.value: plug(name, Slot.RUNNER)} if kind is DeterministicSpec else {})

    def _craft_one(self, semantic: float, name: str, **pins: Any) -> Spec[str]:
        kind = self._craft_kind(semantic)
        return self._craft_spec(kind, name, output=self._craft_output(), **self._craft_plugs(kind, name), **pins)

    ############################################################

    ##### PUBLIC #####

    def craft(
        self,
        section: Section,
        n: int = 8,
        *,
        semantic: float = 0.5,
        fallbacks: int = 1,
        wiki: Iterable[str] = ("net-amount",),
        density: float = 0.4,
    ) -> Blueprint:
        """A coherent section: `n` specs (a `semantic` share of them), a random DAG of `density` edges per
        earlier spec, `fallbacks` fallback-only specs each serving one parent, wiki terms sprinkled — then
        written, with the runners they plug and the wiki pages they name."""
        names = self._craft_names(section, n)
        regular, spare = names[: n - fallbacks], names[n - fallbacks :]
        terms = tuple(wiki)
        backup = dict(zip(self._rng.sample(regular, k=min(fallbacks, len(regular))), spare, strict=False))
        crafted = {
            name: self._craft_one(
                semantic,
                name,
                depends=tuple(earlier for earlier in regular[:index] if self._rng.random() < density),
                fallback=backup.get(name),
                wiki=tuple(term for term in terms if self._rng.random() < 0.5),
            )
            for index, name in enumerate(regular)
        } | {name: self._craft_one(semantic, name, depends=(), fallback=None, wiki=()) for name in spare}
        blueprint = Blueprint(section=section, specs=crafted)
        _ = [self.write_spec(section, spec) for spec in crafted.values()]
        _ = [
            self.write_runner(section, ref.partition("/")[2], ROLES[slot])
            for plugs in blueprint.plugs.values()
            for slot, ref in plugs.items()
        ]
        _ = [self.write_wiki(term) for term in terms]
        return blueprint

    def discover(self, **options: Any) -> SpecDiscover:
        return SpecDiscover(self.pipeline, specs=self.specs, runners=self.runners, **options)

    ##### WRITING — the same channels a real pipeline is written through #####

    def spec_file(self, section: Section, name: str) -> Path:
        return self.specs / self.pipeline / section / f"{name}.yaml"

    def runner_file(self, section: Section, module: str) -> Path:
        return self.runners / "owned" / self.pipeline / section / f"{module}.py"

    def tool_file(self, capability: str, module: str) -> Path:
        return self.runners / "agnostic" / capability / f"{module}.py"

    def write_spec(self, section: Section, spec: Spec[str], name: str | None = None) -> Path:
        """A spec as YAML, encoded through the checked hooks — exactly what a human would commit."""
        return self.write_raw(section, name or spec.name, msgspec.to_builtins(spec, enc_hook=CheckedStruct.enc_hook))

    def write_raw(self, section: Section, name: str, document: Any) -> Path:
        """Any document as a spec file — a mapping is dumped as YAML, a string written verbatim."""
        text = document if isinstance(document, str) else eserde.dumps(document, format="yaml").decode()
        return self._write(self.spec_file(section, name), text)

    def read_raw(self, section: Section, name: str) -> dict[str, Any]:
        return eserde.loads(self.spec_file(section, name).read_text(), format="yaml")

    def patch(self, section: Section, spec: str, /, **changes: Any) -> Path:
        """Rewrite a spec's YAML with fields changed — `...` (Ellipsis) drops a field — never through the model."""
        document = {**self.read_raw(section, spec), **changes}
        return self.write_raw(section, spec, {key: value for key, value in document.items() if value is not ...})

    def write_runner(self, section: Section, module: str, role: Role | None, **parts: Any) -> Path:
        """An owned runner module of the section: its role function by contract (`render`), plus raw parts."""
        return self._write(self.runner_file(section, module), self.module(module, role, **parts))

    def write_tool(self, capability: str, module: str, role: Role | None, **parts: Any) -> Path:
        """An agnostic tool module of a capability, written as an owned one is."""
        return self._write(self.tool_file(capability, module), self.module(module, role, **parts))

    @classmethod
    def module(
        cls,
        name: str,
        role: Role | None,
        *,
        functions: str = "",
        imports: str = "",
        args: str = "",
        **render: Any,
    ) -> str:
        """A runner module's source: imports, an optional `Args` body, the role's function, any extra functions."""
        declared = f"\n\nclass Args(CheckedStruct, frozen=True, kw_only=True):\n{args}" if args else ""
        checked = "from infra.struct import CheckedStruct\n" if args else ""
        blocks = [cls.render(role, **render)] if role is not None else []
        body = "\n\n".join([*blocks, functions] if functions else blocks)
        return f'"""{name}: crafted runner."""\n\n{imports}{checked}{HEADER}{declared}\n\n{body}\n'

    @staticmethod
    def render(
        role: Role, *, signature: str | None = None, doc: str | None = "Crafted runner.", body: str | None = None
    ) -> str:
        """One role function from its contract; `signature`/`doc`/`body` override it — to break it on purpose."""
        docstring = f'    """{doc}"""\n' if doc else ""
        lines = "".join(f"    {line}\n" for line in (body or BODIES[role]).splitlines())
        return f"{signature or SIGNATURES[role]}:\n{docstring}{lines}"

    def write_wiki(self, term: str, *, shared: bool = True) -> Path:
        folder = self.specs / "wiki" if shared else self.specs / self.pipeline / "wiki"
        return self._write(folder / f"{term}.md", f"# {term}\n")

    @staticmethod
    def _write(path: Path, text: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path
