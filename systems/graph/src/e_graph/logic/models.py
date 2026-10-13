"""logic.models: the DARTS core's own data — the agent's vocabulary and the spec catalog's.

Everything the engine speaks lives here and only here.

AGENT. `Provider` mirrors any-llm's 52 providers value for value, plus `CUSTOM` (any OpenAI-compatible
endpoint); `Endpoint` is where and as whom a model is reached, every connection field optional so the
agent can fill it from settings, the provider's environment or, for local servers, a dummy key.
`Shape[T]` is an output model resolved for the wire; `Reply[T]` is one structured call's result: the
validated output and what it cost.

SPECS. A spec is a YAML file, `specs/<pipeline>/<section>/<name>.yaml`, decoded into a tagged union
(`kind`) of `Spec` subclasses: `DeterministicSpec` and `SemanticSpec`, or a pipeline's own extension.
`Spec` is generic over its name type: `Spec.named(section)` is the section's own regex (`EXT-…` for
extract), so a name, every `depends` entry and the `fallback` are validated against the section the
file lives in — by msgspec, while decoding. What one document can say about itself is checked here, in
`__post_init__`; what only the whole section can answer is `logic.rules`' work. A spec's runners live
in the module of the same name, `runners/<pipeline>/<section>/<name>.py`, as fixed hook functions:
`run`, `check`, `pre_run`, `post_run` — discovered, never declared."""

import annotationlib
from collections.abc import Callable
from datetime import timedelta
from enum import StrEnum, auto
from functools import cache
from types import MappingProxyType
from typing import TYPE_CHECKING, Annotated, Any, ClassVar, Final

import jsonschema_rs
import msgspec

from core.struct import CheckedStruct
from e_graph.models.section import PREFIXES, Section

if TYPE_CHECKING:
    from collections.abc import Mapping


##### PROVIDERS #####
class Provider(StrEnum):
    """Every model provider the agent can reach; the value is any-llm's own provider id."""

    ANTHROPIC = auto()
    BEDROCK = auto()
    AZURE = auto()
    AZUREANTHROPIC = auto()
    AZUREOPENAI = auto()
    ATLASCLOUD = auto()
    CASCADIA = auto()
    CEREBRAS = auto()
    COHERE = auto()
    DATABRICKS = auto()
    DEEPSEEK = auto()
    FIREWORKS = auto()
    GEMINI = auto()
    GITHUB = auto()
    GMI = auto()
    GROQ = auto()
    HUGGINGFACE = auto()
    INCEPTION = auto()
    KENARI = auto()
    LLAMA = auto()
    LMSTUDIO = auto()
    LLAMAFILE = auto()
    LLAMACPP = auto()
    META = auto()
    MISTRAL = auto()
    MOONSHOT = auto()
    MZAI = auto()
    NEOSANTARA = auto()
    NEBIUS = auto()
    OLLAMA = auto()
    OPENAI = auto()
    OTARI = auto()
    OPENROUTER = auto()
    PORTKEY = auto()
    QINIU = auto()
    REQUESTY = auto()
    SAMBANOVA = auto()
    SAGEMAKER = auto()
    TOGETHER = auto()
    VERTEXAI = auto()
    VERTEXAIANTHROPIC = auto()
    VLLM = auto()
    VOYAGE = auto()
    WATSONX = auto()
    XAI = auto()
    PERPLEXITY = auto()
    MINIMAX = auto()
    DASHSCOPE = auto()
    DEEPINFRA = auto()
    EDENAI = auto()
    ZAI = auto()
    TELNYX = auto()
    CUSTOM = auto()


### servers that run on your own hardware: they take no key, but their clients may insist on one.
LOCAL: Final[frozenset[Provider]] = frozenset(
    {
        Provider.OLLAMA,
        Provider.LLAMAFILE,
        Provider.LLAMACPP,
        Provider.LMSTUDIO,
        Provider.VLLM,
        Provider.CUSTOM,
    }
)
### providers whose structured output runs in strict mode: every property required, nothing extra allowed.
STRICT: Final[frozenset[Provider]] = frozenset({Provider.OPENAI, Provider.AZUREOPENAI, Provider.AZURE})


class Tier(StrEnum):
    """A model class chosen by capability, resolved to an endpoint by settings (AGENT_HIGH / _MEDIUM / _LOW)."""

    HIGH = auto()
    MEDIUM = auto()
    LOW = auto()


class Role(StrEnum):
    """Who speaks a message, in the chat standard every provider accepts."""

    SYSTEM = auto()
    USER = auto()
    ASSISTANT = auto()


##### CALL #####
class Endpoint(msgspec.Struct, frozen=True, kw_only=True):
    """Where and as whom: a provider, a model, and the connection — empty fields filled at run time.

    `api_base` and `api_key` resolve, first wins: the `run` call's own arguments, these fields, the
    provider's settings (its standard variables), then a dummy key for local servers. `options` reach the
    provider's client as is (region, project, api_version...)."""

    provider: Provider
    model: str
    api_base: str = ""
    api_key: str = ""
    options: dict[str, Any] = msgspec.field(default_factory=dict)

    def __repr__(self) -> str:
        ### a key never reaches a log or a traceback through a repr.
        key = "***" if self.api_key else ""
        return (
            f"Endpoint(provider={self.provider!r}, model={self.model!r}, api_base={self.api_base!r}, api_key={key!r})"
        )


class Message(msgspec.Struct, frozen=True):
    """One turn of a conversation."""

    role: Role
    content: str


##### RESULT #####
class Usage(msgspec.Struct, frozen=True, kw_only=True):
    """What model calls cost: tokens in, tokens out, and how many calls added up to them."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    calls: int = 0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            calls=self.calls + other.calls,
        )


class Completion(msgspec.Struct, frozen=True, kw_only=True):
    """One provider answer as the agent judges it: the text, its cost, who answered, and why it stopped."""

    raw: str
    usage: Usage
    model: str
    finish: str = ""
    refusal: str = ""


class Reply[T](msgspec.Struct, frozen=True, kw_only=True):
    """One structured call's result: the validated output, who produced it, what it cost, how many tries."""

    output: T
    provider: Provider
    model: str
    usage: Usage
    latency_ms: float
    attempts: int


class Shape[T](msgspec.Struct, frozen=True, kw_only=True):
    """An output resolved once, before any call: its name and JSON Schema for the provider, and the parse back.

    `parse` turns the raw reply into `T` or raises one of `errors` — the agent's cue to retry."""

    name: str
    schema: dict[str, Any]
    parse: Callable[[str], T]
    errors: tuple[type[Exception], ...]


##### SPECS #####
### every spec name's tail after its section prefix, and a wiki term: lowercase words joined by single hyphens.
WORDS: Final[str] = r"[a-z0-9]+(?:-[a-z0-9]+)*"

### a spec name of any section: the bound a spec built in code is held to; a section's own catalog narrows it.
ANY_NAME: Final[str] = f"^(?:{'|'.join(PREFIXES.values())})-{WORDS}$"

type Text = Annotated[str, msgspec.Meta(min_length=1, pattern=r"\S")]
type WikiTerm = Annotated[str, msgspec.Meta(pattern=f"^{WORDS}$")]
type AnyName = Annotated[str, msgspec.Meta(pattern=ANY_NAME, description="a spec name of any section")]


class JsonSchema(dict[str, Any]):
    """A JSON Schema with an object root, valid against its meta-schema — a checked type: validated by being built.

    `validator` is compiled once, here, by jsonschema-rs: every example and every reply is checked against
    it, never recompiled. Decodes through `CheckedStruct.dec_hook`, encodes as the plain dict it is."""

    __slots__ = ("validator",)

    def __init__(self, value: Any = (), /) -> None:
        super().__init__(value)
        match self:
            case {"type": "object"} if jsonschema_rs.meta.is_valid(dict(self)):
                self.validator = jsonschema_rs.validator_for(dict(self))
            case {"type": "object"}:
                msg = "no valid JSON Schema: it breaks the meta-schema"
                raise ValueError(msg)
            case _:
                msg = 'a JSON Schema needs an object root: {"type": "object", ...}'
                raise ValueError(msg)


class Bound(StrEnum):
    """What a spec's work waits on: the network and the model (most), or the CPU (a heavy deterministic pass)."""

    IO = auto()
    CPU = auto()


class Hook(StrEnum):
    """A runner's role, and the one name its function may have inside the spec's runner module."""

    RUN = "run"
    CHECK = "check"
    PRE = "pre_run"
    POST = "post_run"


### each hook's whole contract, as its signature reads — the discovery compares it verbatim, importing nothing.
SIGNATURES: Final[Mapping[Hook, str]] = MappingProxyType(
    {
        Hook.RUN: "async def run(state: RunState) -> dict[str, Any]",
        Hook.CHECK: "async def check(state: RunState) -> bool",
        Hook.PRE: "async def pre_run(state: RunState) -> str",
        Hook.POST: "async def post_run(state: RunState, output: dict[str, Any]) -> dict[str, Any]",
    }
)


class Spec[N: AnyName](CheckedStruct, frozen=True, kw_only=True, forbid_unknown_fields=True, tag_field="kind"):
    """What every spec says: who it is, what it produces, what it needs, and how it fails over.

    A `CheckedStruct`: decoded or built in code, it is validated the same way — each field by its type
    (`JsonSchema`, the name regex), the fields against each other in `_check`. Built in code, its names
    are held to any section's prefix (the `AnyName` bound); decoded into a section, to that section's.
    `output` is the JSON Schema of what the spec produces. `depends` and `fallback` name specs of the same
    section; `fallback` runs only when this spec fails. `wiki` names terms explained under
    `specs/[<pipeline>/]wiki/<term>.md`. Extend by subclassing with a new `tag` (and `frozen=True,
    kw_only=True`); redefining an inherited field is refused."""

    HOOKS: ClassVar[frozenset[Hook]] = frozenset({Hook.CHECK})
    REQUIRED: ClassVar[frozenset[Hook]] = frozenset()

    name: N
    description: Text
    output: JsonSchema
    depends: tuple[N, ...] = ()
    fallback: N | None = None
    wiki: tuple[WikiTerm, ...] = ()
    bound: Bound = Bound.IO
    timeout: timedelta | None = None
    version: Annotated[int, msgspec.Meta(ge=1)] = 1

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        own = annotationlib.get_annotations(cls, format=annotationlib.Format.FORWARDREF)
        inherited = {name for base in cls.__bases__ for name in getattr(base, "__struct_fields__", ())}
        match sorted(set(own) & inherited):
            case []:
                pass
            case clash:
                msg = f"{cls.__name__} redefines inherited spec fields {clash}: extend a spec, never reshape it"
                raise TypeError(msg)

    def _check(self) -> None:
        problems = [
            message
            for broken, message in (
                (self.name in self.depends, "a spec cannot depend on itself"),
                (len(set(self.depends)) < len(self.depends), "depends repeats a spec"),
                (self.fallback == self.name, "a spec cannot be its own fallback"),
                (self.fallback in self.depends, "the fallback cannot also be a dependency"),
                (len(set(self.wiki)) < len(self.wiki), "wiki repeats a term"),
                (self.timeout is not None and self.timeout <= timedelta(0), "timeout must be positive"),
            )
            if broken
        ]
        match problems:
            case []:
                pass
            case _:
                raise ValueError("; ".join(problems))

    ############################################################

    @classmethod
    @cache
    def named(cls, section: Section) -> Any:
        """The section's name type: its prefix, a hyphen, lowercase words — `EXT-total-amount`."""
        pattern = f"^{PREFIXES[section]}-{WORDS}$"
        return Annotated[str, msgspec.Meta(pattern=pattern, description=f"a {section} spec name")]


class DeterministicSpec[N: AnyName](Spec[N], frozen=True, tag="deterministic"):
    """A spec computed by code: its runner module must define `run`, may define `check`."""

    HOOKS: ClassVar[frozenset[Hook]] = frozenset({Hook.RUN, Hook.CHECK})
    REQUIRED: ClassVar[frozenset[Hook]] = frozenset({Hook.RUN})


class SemanticSpec[N: AnyName](Spec[N], frozen=True, kw_only=True, tag="semantic"):
    """A spec answered by the agent: `instructions` asked at `tier`, `output` its structured reply.

    Its runner module is optional: `pre_run` prepares what the prompt carries, `post_run` reshapes the
    validated reply, `check` gates it. `examples` are few-shot replies, each valid against `output`."""

    HOOKS: ClassVar[frozenset[Hook]] = frozenset({Hook.PRE, Hook.POST, Hook.CHECK})

    instructions: Text
    tier: Tier = Tier.MEDIUM
    examples: tuple[dict[str, Any], ...] = ()

    def _check(self) -> None:
        super()._check()
        match [index for index, example in enumerate(self.examples) if not self.output.validator.is_valid(example)]:
            case []:
                pass
            case wrong:
                msg = f"examples {wrong} do not match output"
                raise ValueError(msg)


##### CATALOG #####
class Function(msgspec.Struct, frozen=True, kw_only=True):
    """A top-level function of a runner module, as the source says it — read by AST, never imported."""

    name: str
    signature: str
    doc: str
    file: str


class Runner(msgspec.Struct, frozen=True, kw_only=True):
    """One hook of one spec, discovered: its role, where it lives, and its docstring — required."""

    spec: str
    hook: Hook
    file: str
    doc: Text

    @property
    def name(self) -> str:
        """`<spec>.<hook>` — the runner named by what it serves and the role it plays."""
        return f"{self.spec}.{self.hook}"


class Draft(msgspec.Struct, frozen=True, kw_only=True):
    """A section as found on disk, before the rules judge it: decoded specs, runner functions, wiki terms.

    `broken` names the spec files that exist but did not decode: their own breach is already reported,
    so the section laws count them as present — no orphan runner, no missing dependency in cascade."""

    pipeline: str
    section: Section
    specs: dict[str, Spec[str]]
    functions: dict[str, tuple[Function, ...]]
    wiki: frozenset[str]
    broken: frozenset[str] = frozenset()

    @property
    def known(self) -> frozenset[str]:
        """Every spec name the section holds a file for, decoded or not."""
        return frozenset(self.specs) | self.broken


class SpecNode(msgspec.Struct, frozen=True, kw_only=True):
    """A spec and its runners: the unit the orchestrator schedules."""

    spec: Spec[str]
    file: str
    hooks: dict[Hook, Runner] = msgspec.field(default_factory=dict)


class Catalog(msgspec.Struct, frozen=True, kw_only=True):
    """One section of one pipeline, judged coherent: every spec paired with its runners, by name."""

    pipeline: str
    section: Section
    nodes: dict[str, SpecNode]
