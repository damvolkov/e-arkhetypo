"""tests/support/crafter: craft a coherent DARTS pipeline on disk — then break it, one law at a time.

`SpecCrafter` builds specs the way production code would: in Python, as `CheckedStruct`s, so every
crafted spec is validated at birth. pytest-resources (`resources.make`, polyfactory) fills every
free field at random — description, instructions, tier, bound, version — while the crafter pins
the structure it must control: names, the dependency DAG, fallbacks, wiki terms, schemas, timeouts.
Each spec is written as YAML (e-serde), its runner module rendered from the hook contracts, its
wiki terms as markdown: a tree `SpecDiscover` reads exactly as it would read a real pipeline.

The `Blueprint` remembers what was crafted — the specs, the hooks each runner defines, the edges —
so a test compares the catalog against intent, and picks the spec a breach should hit."""

import random
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final

import eserde
import msgspec

from core.struct import CheckedStruct
from e_graph.logic.discover import SpecDiscover
from e_graph.logic.models import SIGNATURES, DeterministicSpec, Hook, JsonSchema, SemanticSpec, Spec
from e_graph.models.section import PREFIXES, Section

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
BODIES: Final[Mapping[Hook, str]] = {
    Hook.RUN: "return {}",
    Hook.CHECK: "return True",
    Hook.PRE: 'return ""',
    Hook.POST: "return output",
}
WORDS: Final[tuple[str, ...]] = ("total", "net", "tax", "line", "page", "party", "date", "fee", "sum", "ratio")


@dataclass(slots=True)
class Blueprint:
    """What was crafted for one section: the specs by name and the hooks each runner module defines."""

    section: Section
    specs: dict[str, Spec[str]] = field(default_factory=dict)
    hooks: dict[str, frozenset[Hook]] = field(default_factory=dict)

    @property
    def deterministic(self) -> list[str]:
        return [name for name, spec in self.specs.items() if isinstance(spec, DeterministicSpec)]

    @property
    def semantic(self) -> list[str]:
        return [name for name, spec in self.specs.items() if isinstance(spec, SemanticSpec)]

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
        return self._resources.make(kind, seed=seed, name=name, timeout=timeout, **extra, **pins)

    def _craft_kind(self, semantic: float) -> type[Spec[str]]:
        return SemanticSpec if self._rng.random() < semantic else DeterministicSpec

    def _craft_hooks(self, spec: Spec[str]) -> frozenset[Hook]:
        """The hooks its runner module will define: `run` always for deterministic, any optional subset beside."""
        optional = sorted(type(spec).HOOKS - type(spec).REQUIRED)
        chosen = {hook for hook in optional if self._rng.random() < 0.5}
        return frozenset(type(spec).REQUIRED | chosen)

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
        written, with their runners and the wiki pages they name."""
        names = self._craft_names(section, n)
        regular, spare = names[: n - fallbacks], names[n - fallbacks :]
        terms = tuple(wiki)
        backup = dict(zip(self._rng.sample(regular, k=min(fallbacks, len(regular))), spare, strict=False))
        crafted = {
            name: self._craft_spec(
                self._craft_kind(semantic),
                name,
                depends=tuple(earlier for earlier in regular[:index] if self._rng.random() < density),
                fallback=backup.get(name),
                wiki=tuple(term for term in terms if self._rng.random() < 0.5),
                output=self._craft_output(),
            )
            for index, name in enumerate(regular)
        } | {
            name: self._craft_spec(
                self._craft_kind(semantic), name, depends=(), fallback=None, wiki=(), output=self._craft_output()
            )
            for name in spare
        }
        blueprint = Blueprint(
            section=section, specs=crafted, hooks={name: self._craft_hooks(spec) for name, spec in crafted.items()}
        )
        _ = [self.write_spec(section, spec) for spec in crafted.values()]
        _ = [self.write_runner(section, name, hooks) for name, hooks in blueprint.hooks.items()]
        _ = [self.write_wiki(term) for term in terms]
        return blueprint

    def discover(self, **options: Any) -> SpecDiscover:
        return SpecDiscover(self.pipeline, specs=self.specs, runners=self.runners, **options)

    ##### WRITING — the same channels a real pipeline is written through #####

    def spec_file(self, section: Section, name: str) -> Path:
        return self.specs / self.pipeline / section / f"{name}.yaml"

    def runner_file(self, section: Section, name: str) -> Path:
        return self.runners / self.pipeline / section / f"{name}.py"

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

    def write_runner(self, section: Section, name: str, hooks: Iterable[Hook], *, functions: str = "") -> Path | None:
        """A runner module defining `hooks` by their contracts (plus raw `functions`); none when nothing to define."""
        rendered = [self.render(hook) for hook in sorted(hooks)]
        match [*rendered, functions] if functions else rendered:
            case []:
                return None
            case blocks:
                header = f'"""{name}: crafted runner."""\n\nfrom typing import Any\n\nfrom e_graph.instrument.state import RunState\n'
                return self._write(self.runner_file(section, name), "\n\n".join([header, *blocks]) + "\n")

    @staticmethod
    def render(hook: Hook, *, signature: str | None = None, doc: str | None = "Crafted hook.") -> str:
        """One hook function from its contract; `signature`/`doc` override it to break the contract on purpose."""
        docstring = f'    """{doc}"""\n' if doc else ""
        return f"{signature or SIGNATURES[hook]}:\n{docstring}    {BODIES[hook]}\n"

    def write_wiki(self, term: str, *, shared: bool = True) -> Path:
        folder = self.specs / "wiki" if shared else self.specs / self.pipeline / "wiki"
        return self._write(folder / f"{term}.md", f"# {term}\n")

    @staticmethod
    def _write(path: Path, text: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path
