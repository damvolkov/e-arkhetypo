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
`__post_init__`; what only the whole section can answer is `logic.rules`' work. A spec plugs runners by
reference, one per `Slot`: `owned/<name>` (`runners/owned/<pipeline>/<section>/<name>.py`) or
`agnostic/<capability>/<name>` (`runners/agnostic/<capability>/<name>.py`). A runner module holds one
function named by its `Role` (`run`, `check`, `pre_run`, `post_run`), with the role's `SIGNATURES` entry.

REPORT. `Report` is the static check of the whole system: every `Breach`, errors and warnings, as data."""

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
from e_graph.logic.errors import Rule, Severity
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


class Speaker(StrEnum):
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

    role: Speaker
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


class Role(StrEnum):
    """What a runner does — and the one name its single function may have in its module."""

    RUN = "run"
    CHECK = "check"
    PRE = "pre_run"
    POST = "post_run"


class Slot(StrEnum):
    """Where a spec plugs a runner: `runner` produces (deterministic), `pre`/`post` frame the agent's answer
    (semantic), `check` gates the state (both)."""

    RUNNER = "runner"
    CHECK = "check"
    PRE = "pre"
    POST = "post"


class Scope(StrEnum):
    """Where a runner lives: `owned` by one pipeline and section, or `agnostic` — a tool any spec may plug."""

    OWNED = auto()
    AGNOSTIC = auto()


### the role a slot accepts: a runner plugged in the wrong slot is refused — a check never prepares, a pre never gates.
ROLES: Final[Mapping[Slot, Role]] = MappingProxyType(
    {Slot.RUNNER: Role.RUN, Slot.CHECK: Role.CHECK, Slot.PRE: Role.PRE, Slot.POST: Role.POST}
)
### each role's whole contract, as its signature reads — the discovery compares it verbatim, by AST.
SIGNATURES: Final[Mapping[Role, str]] = MappingProxyType(
    {
        Role.RUN: "async def run(state: RunState, call: Call) -> dict[str, Any]",
        Role.CHECK: "async def check(state: RunState, call: Call) -> bool",
        Role.PRE: "async def pre_run(state: RunState, call: Call) -> str",
        Role.POST: "async def post_run(state: RunState, call: Call, output: dict[str, Any]) -> dict[str, Any]",
    }
)
### a runner reference: `owned/<name>` (the spec's own pipeline and section) or `agnostic/<capability>/<name>`.
REF: Final[str] = r"^(?:owned/[a-z][a-z0-9]*|agnostic/[a-z][a-z0-9]*/[a-z][a-z0-9]*)$"

type RunnerRef = Annotated[str, msgspec.Meta(pattern=REF, description="owned/<name> or agnostic/<capability>/<name>")]
### where a spec's output lives in a run's context: `<section>/<spec>` — `state.context.<section>[<spec>]`.
ADDRESS: Final[str] = rf"^[a-z]+/(?:{'|'.join(PREFIXES.values())})-{WORDS}$"
type Address = Annotated[str, msgspec.Meta(pattern=ADDRESS, description="<section>/<spec>: an output in the context")]


class Spec[N: AnyName](CheckedStruct, frozen=True, kw_only=True, forbid_unknown_fields=True, tag_field="kind"):
    """What every spec says: who it is, what it produces, what it needs, and how it fails over.

    A `CheckedStruct`: decoded or built in code, it is validated the same way — each field by its type
    (`JsonSchema`, the name regex), the fields against each other in `_check`. Built in code, its names
    are held to any section's prefix (the `AnyName` bound); decoded into a section, to that section's.
    `output` is the JSON Schema of what the spec produces. `depends` and `fallback` name specs of the same
    section; `fallback` runs only when this spec fails. Runners are plugged by reference, one per slot
    (`check` here; `runner`, `pre`, `post` by kind), each configured by its `args[slot]`. `wiki` names
    terms explained under `specs/wiki/<term>.md`. Extend by subclassing with a new `tag` (and `frozen=True,
    kw_only=True`); redefining an inherited field is refused."""

    SLOTS: ClassVar[tuple[Slot, ...]] = (Slot.CHECK,)

    name: N
    description: Text
    output: JsonSchema
    depends: tuple[N, ...] = ()
    fallback: N | None = None
    check: RunnerRef | None = None
    args: dict[Slot, dict[str, Any]] = msgspec.field(default_factory=dict)
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
                (
                    not set(self.args) <= set(self.plugs),
                    f"args name slots it does not plug: {sorted(str(slot) for slot in set(self.args) - set(self.plugs))}",
                ),
            )
            if broken
        ]
        match problems:
            case []:
                pass
            case _:
                raise ValueError("; ".join(problems))

    ############################################################

    @property
    def plugs(self) -> dict[Slot, str]:
        """The runners this spec plugs, by slot — only the slots its kind has, only those it fills."""
        return {slot: ref for slot in self.SLOTS if (ref := getattr(self, slot.value)) is not None}

    @classmethod
    @cache
    def named(cls, section: Section) -> Any:
        """The section's name type: its prefix, a hyphen, lowercase words — `EXT-total-amount`."""
        pattern = f"^{PREFIXES[section]}-{WORDS}$"
        return Annotated[str, msgspec.Meta(pattern=pattern, description=f"a {section} spec name")]


class DeterministicSpec[N: AnyName](Spec[N], frozen=True, kw_only=True, tag="deterministic"):
    """A spec computed by code: `runner` (role `run`) produces its output; `check` may gate it."""

    SLOTS: ClassVar[tuple[Slot, ...]] = (Slot.RUNNER, Slot.CHECK)

    runner: RunnerRef


class SemanticSpec[N: AnyName](Spec[N], frozen=True, kw_only=True, tag="semantic"):
    """A spec answered by the agent: `instructions` asked at `tier`, `output` its structured reply.

    Its runners are optional: `pre` (role `pre_run`) prepares what the prompt carries, `post` (role
    `post_run`) reshapes the validated reply, `check` gates the state. `examples` are few-shot replies,
    each valid against `output`."""

    SLOTS: ClassVar[tuple[Slot, ...]] = (Slot.PRE, Slot.POST, Slot.CHECK)

    pre: RunnerRef | None = None
    post: RunnerRef | None = None
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
class Call(msgspec.Struct, frozen=True, kw_only=True):
    """What a runner is handed beside the state: who calls it, how it is configured, what its spec reads.

    `args` is the runner's own `Args` (a `CheckedStruct` its module declares), validated from the spec's
    `args[slot]` — or `{}` for a runner that takes none. `inputs` are the outputs of the spec's
    dependencies, by name: a runner reads its inputs here, never by guessing paths in the context."""

    pipeline: str
    section: Section
    spec: str
    slot: Slot
    args: Any = msgspec.field(default_factory=dict)
    inputs: dict[str, Any] = msgspec.field(default_factory=dict)


class Function(msgspec.Struct, frozen=True, kw_only=True):
    """A top-level function of a runner module, as the source says it — read by AST, never imported."""

    name: str
    signature: str
    doc: str


class Module(msgspec.Struct, frozen=True, kw_only=True):
    """A runner module as found: where it is, and its top-level functions (absent file: `exists` False)."""

    ref: str
    file: str
    exists: bool
    functions: tuple[Function, ...] = ()


class Runner(msgspec.Struct, frozen=True, kw_only=True):
    """A runner plugged in a slot, resolved: its reference, role, file and docstring — required."""

    ref: str
    role: Role
    file: str
    doc: Text

    @property
    def scope(self) -> Scope:
        return Scope(self.ref.partition("/")[0])


class Draft(msgspec.Struct, frozen=True, kw_only=True):
    """A section as found on disk, before the rules judge it: decoded specs, the runner modules they plug,
    the owned modules of the section, the wiki terms in reach.

    `broken` names the spec files that exist but did not decode: their own breach is already reported,
    so the section laws count them as present — no missing dependency in cascade."""

    pipeline: str
    section: Section
    specs: dict[str, Spec[str]]
    modules: dict[str, Module]
    owned: frozenset[str]
    wiki: frozenset[str]
    broken: frozenset[str] = frozenset()

    @property
    def known(self) -> frozenset[str]:
        """Every spec name the section holds a file for, decoded or not."""
        return frozenset(self.specs) | self.broken

    @property
    def plugged(self) -> frozenset[str]:
        """Every owned module name some spec of the section plugs."""
        return frozenset(
            ref.partition("/")[2]
            for spec in self.specs.values()
            for ref in spec.plugs.values()
            if ref.startswith("owned/")
        )


class SpecNode(msgspec.Struct, frozen=True, kw_only=True):
    """A spec, the runners it plugs by slot, and each slot's validated `args`: the unit the orchestrator schedules."""

    spec: Spec[str]
    file: str
    runners: dict[Slot, Runner] = msgspec.field(default_factory=dict)
    args: dict[Slot, Any] = msgspec.field(default_factory=dict)


class Catalog(msgspec.Struct, frozen=True, kw_only=True):
    """One section of one pipeline, judged coherent: every spec paired with its runners, by name, and the
    wiki pages its specs name (term → markdown), handed to the agent beside their instructions."""

    pipeline: str
    section: Section
    nodes: dict[str, SpecNode]
    wiki: dict[str, str] = msgspec.field(default_factory=dict)


##### REPORT #####
class Breach(msgspec.Struct, frozen=True, kw_only=True):
    """One broken law, as data: what a `RuleError` says, ready to print or serialize."""

    rule: Rule
    subject: str
    detail: str
    severity: Severity = Severity.ERROR


class Report(msgspec.Struct, frozen=True, kw_only=True):
    """The static check of the whole system: what was judged, and every breach found — errors fail it."""

    pipelines: tuple[str, ...]
    sections: int
    specs: int
    breaches: tuple[Breach, ...] = ()

    @property
    def errors(self) -> tuple[Breach, ...]:
        return tuple(breach for breach in self.breaches if breach.severity is Severity.ERROR)

    @property
    def warnings(self) -> tuple[Breach, ...]:
        return tuple(breach for breach in self.breaches if breach.severity is Severity.WARNING)

    @property
    def ok(self) -> bool:
        return not self.errors


##### ORCHESTRATION #####
class SpecStatus(StrEnum):
    """How a spec ended in a run.

    `succeeded` — it produced a valid output; `rescued` — it failed and its fallback produced one in its
    place; `failed` — it (and its fallback, if any) produced none; `blocked` — its `check` refused the
    data in the state, so it never ran on corrupt input; `skipped` — a dependency did not deliver."""

    SUCCEEDED = auto()
    RESCUED = auto()
    FAILED = auto()
    BLOCKED = auto()
    SKIPPED = auto()

    @property
    def delivered(self) -> bool:
        """Whether an output exists under the spec's name for its dependents to read."""
        return self in {SpecStatus.SUCCEEDED, SpecStatus.RESCUED}


class FusedCall(msgspec.Struct, frozen=True, kw_only=True):
    """Semantic specs of one step and one tier, answered by one agent call."""

    tier: Tier
    specs: tuple[str, ...]


class Step(msgspec.Struct, frozen=True, kw_only=True):
    """One topological generation of the section's DAG: everything in it runs at once."""

    index: int
    deterministic: tuple[str, ...] = ()
    fused: tuple[FusedCall, ...] = ()

    @property
    def specs(self) -> tuple[str, ...]:
        """Every spec the step runs, deterministic first."""
        return (*self.deterministic, *(name for call in self.fused for name in call.specs))


class SectionPlan(msgspec.Struct, frozen=True, kw_only=True):
    """How a section runs: its steps in order, and the fallbacks held back for their parents (parent → fallback)."""

    pipeline: str
    section: Section
    steps: tuple[Step, ...]
    fallbacks: dict[str, str] = msgspec.field(default_factory=dict)


class SpecOutcome(msgspec.Struct, frozen=True, kw_only=True):
    """One spec in one run: where it ran, how it ended, what it cost — the ledger line the audit reads.

    `rescuer` names the fallback that produced the output of a rescued spec; `call` the fused call that
    answered a semantic one (its `usage` is that call's, shared by the specs it answered)."""

    spec: str
    kind: str
    step: int
    status: SpecStatus
    latency_ms: float = 0.0
    reason: str = ""
    error: str = ""
    rescuer: str = ""
    call: int = -1
    usage: Usage | None = None


class AgentCall(msgspec.Struct, frozen=True, kw_only=True):
    """One agent call exactly as the orchestrator issued it: the fused instructions, prompt and schema, the
    tier it went to, the specs it answers, what each weighed against the budget — the payload, whole."""

    index: int
    step: int
    tier: Tier
    specs: tuple[str, ...]
    instructions: str
    prompt: str
    schema: dict[str, Any]
    weights: dict[str, int] = msgspec.field(default_factory=dict)
    budget: int = 0


class SectionRun(msgspec.Struct, frozen=True, kw_only=True):
    """A section run: its plan, every spec's outcome in plan order, every agent call it issued, and how long it took."""

    pipeline: str
    section: Section
    plan: SectionPlan
    outcomes: tuple[SpecOutcome, ...]
    latency_ms: float
    calls: tuple[AgentCall, ...] = ()

    @property
    def counts(self) -> dict[SpecStatus, int]:
        """How many specs ended in each status."""
        return {
            status: sum(o.status is status for o in self.outcomes)
            for status in SpecStatus
            if any(o.status is status for o in self.outcomes)
        }

    @property
    def summary(self) -> str:
        """One line: specs, steps, and how they ended."""
        ended = ", ".join(f"{count} {status}" for status, count in self.counts.items())
        return f"{len(self.outcomes)} specs in {len(self.plan.steps)} steps: {ended or 'nothing to run'}"


##### LAB #####
class LinkKind(StrEnum):
    """What ties two specs in a section's drawing: a dependency it reads, or the fallback it holds."""

    DEPENDS = auto()
    FALLBACK = auto()


class SpecPoint(msgspec.Struct, frozen=True, kw_only=True):
    """A spec placed on the section's map: its step is its rank, its lane its place in the step.

    `call` is the planned fused call that answers a semantic spec (-1 otherwise); `rescues` names the parent
    a fallback stands in for (it sits in its parent's step, after the rest)."""

    id: str
    kind: str
    description: str
    rank: int
    lane: int
    tier: str = ""
    call: int = -1
    rescues: str = ""
    runners: dict[Slot, str] = msgspec.field(default_factory=dict)
    wiki: tuple[str, ...] = ()
    output: dict[str, Any] = msgspec.field(default_factory=dict)


class SpecLink(msgspec.Struct, frozen=True, kw_only=True):
    """An arc of the section's map."""

    id: str
    source: str
    target: str
    kind: LinkKind


class CallGroup(msgspec.Struct, frozen=True, kw_only=True):
    """A planned fused call: the specs one agent call answers, in which step and tier, weighed against the budget."""

    index: int
    rank: int
    tier: Tier
    specs: tuple[str, ...]
    weight: int
    budget: int


class SectionMap(msgspec.Struct, frozen=True, kw_only=True):
    """A section as the orchestrator will run it, placed for drawing: specs by step and lane, their arcs, the calls."""

    pipeline: str
    section: Section
    nodes: tuple[SpecPoint, ...]
    edges: tuple[SpecLink, ...]
    calls: tuple[CallGroup, ...]
    ranks: int
    lanes: int


class SectionInfo(msgspec.Struct, frozen=True, kw_only=True):
    """A pipeline's section as the lab lists it: how many specs, steps and planned calls."""

    pipeline: str
    section: Section
    specs: int
    steps: int
    calls: int


class Route(msgspec.Struct, frozen=True, kw_only=True):
    """Where a tier's calls go, the key never shown: provider, model, base — or why the tier has none."""

    provider: str = ""
    model: str = ""
    api_base: str = ""
    error: str = ""


##### OPS #####
class Signal(msgspec.Struct, frozen=True, kw_only=True):
    """One thing a readout found wrong: the `kind` says which layer spoke (an infra tier, a spec's outcome,
    an audit's verdict, a pinned expectation), `where` is its address, and what was seen against what was wanted."""

    kind: str
    where: str
    observed: str = ""
    expected: str = ""
    detail: str = ""


class Readout(msgspec.Struct, frozen=True, kw_only=True):
    """The pipeline evaluated: how every tier answered, each section's summary, and the signals the reading left."""

    pipeline: str
    mode: str
    probe: dict[str, float] = msgspec.field(default_factory=dict)
    summaries: dict[str, str] = msgspec.field(default_factory=dict)
    signals: tuple[Signal, ...] = ()

    @property
    def ok(self) -> bool:
        """The readout is green when nothing spoke: no infra complaint, no failed spec, no broken expectation."""
        return not self.signals


class Simulation(msgspec.Struct, frozen=True, kw_only=True):
    """A section rehearsed: the pipeline run up to it, every section's run, the target's agent calls whole,
    where each tier routes, and what the target section wrote. `live` calls the model; otherwise the agent
    answers each spec from its first example, or the least its schema accepts."""

    pipeline: str
    section: Section
    live: bool
    runs: tuple[SectionRun, ...]
    calls: tuple[AgentCall, ...]
    routes: dict[str, Route]
    written: dict[str, Any]
    latency_ms: float
