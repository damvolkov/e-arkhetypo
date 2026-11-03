"""logic.dartsops: the DARTSOPS reading instruments — the law contract, the tier probe, the evaluated readout.

Three questions, three tools. **Contract**: the grammar and the laws a spec must keep, as one JSON mirror
of `models`/`rules`/`errors` — what a coder reads before touching anything, so the law it obeys is the law
the check enforces. **Probe**: is each tier actually answering? one trivial structured call per tier, timed
— a hung model server is an infra signal and must never be chased as a misread spec. **Evaluate**: run a
pipeline's sections in order over data and report what the reading left behind — every failed, blocked or
skipped spec, every *rescued* one (a deterministic covered by a semantic is drift), every audit that says
it did not hold, every pinned expectation read differently — as `Signal`s: structured evidence a loop can
act on."""

import dataclasses
from functools import reduce
from operator import or_
from time import perf_counter
from typing import TYPE_CHECKING, Any, Final, Protocol, cast

import msgspec

from e_graph.instrument.contexts import InstrumentContexts
from e_graph.instrument.state import RunState
from e_graph.logic.discover import KINDS, RUNNERS, SPECS, SpecDiscover
from e_graph.logic.errors import Rule
from e_graph.logic.models import (
    ADDRESS,
    ANY_NAME,
    REF,
    ROLES,
    SIGNATURES,
    WORDS,
    AnyName,
    DeterministicSpec,
    JsonSchema,
    Readout,
    Reply,
    Role,
    Scope,
    SemanticSpec,
    Signal,
    Tier,
)
from e_graph.models.section import ORDER, PREFIXES, Section
from infra.settings import settings as st
from infra.state import State


class Answers(Protocol):
    """The agent port the instruments call: one structured async run, whatever answers behind it."""

    async def run(
        self, instructions: str, prompt: str, output: Any, *, endpoint: Any = ..., **options: Any
    ) -> Reply[Any]: ...


if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from e_graph.logic.models import SectionRun
    from e_graph.logic.orchestrator.core import OrchestratorCore

PROBE_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "title": "probe",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
}
PROBE_PROMPT: Final[str] = 'Reply with the only answer it allows: {"ok": true}'
LOST: Final[frozenset[str]] = frozenset({"failed", "blocked", "skipped"})
MISSING: Final = object()

### the laws as `docs/darts.md` states them, mirrored for machines: rule → scope, what to do.
LAWS: Final[Mapping[Rule, tuple[str, str]]] = {
    Rule.TREE: ("tree", "move it, rename it to one word, or delete it"),
    Rule.PIPELINE: ("system", "rename the folder, or delete it"),
    Rule.UNMOUNTED: ("system", "add the node, or delete the folder"),
    Rule.DECODE: ("spec", "read the detail: field, type, pattern"),
    Rule.MERGE: ("spec", "write the fields out; anchors and aliases are fine"),
    Rule.FILENAME: ("section", "rename the file or the spec to match"),
    Rule.DEPENDS: ("section", "add the spec, or drop the name"),
    Rule.FALLBACK: ("section", "keep fallbacks leaves: no dependencies, no fallback, nothing depending on it"),
    Rule.CYCLE: ("section", "break one edge"),
    Rule.RUNNER: ("section", "write it, fix the reference or its import"),
    Rule.SHAPE: ("section", "one function per runner module; helpers are methods of Args"),
    Rule.ROLE: ("section", "plug it in its slot, or rename it"),
    Rule.SIGNATURE: ("section", "copy the role's signature exactly"),
    Rule.DOC: ("section", "say what it does, in one docstring line"),
    Rule.ARGS: ("section", "match the runner's Args"),
    Rule.WIKI: ("section", "write specs/wiki/<term>.md or the pipeline's own"),
    Rule.ORPHAN: ("section", "plug it, or delete it"),
    Rule.IDLE: ("system", "plug it, or let it wait — a warning, never a failure"),
}


class DartsOps:
    """The instruments a maintenance loop reads; the judgment — what a signal means, what to do — is the coder's."""

    __slots__ = ("_conf", "_orchestrator", "_runners", "_specs")

    def __init__(self, orchestrator: OrchestratorCore, *, specs: Path = SPECS, runners: Path = RUNNERS) -> None:
        self._orchestrator, self._conf = orchestrator, st.darts
        self._specs, self._runners = specs, runners

    ##### CONTRACT #####

    def contract(self) -> dict[str, Any]:
        """The grammar and the laws as data: kinds by tag, the patterns names and references obey, the role
        signatures, sections with their prefixes, the fusion budgets, every law with its fix."""
        return {
            "kinds": {
                "deterministic": msgspec.json.schema(cast("Any", DeterministicSpec)[AnyName], schema_hook=_schema_hook),
                "semantic": msgspec.json.schema(cast("Any", SemanticSpec)[AnyName], schema_hook=_schema_hook),
                "union": msgspec.json.schema(
                    reduce(or_, (cast("Any", kind)[AnyName] for kind in KINDS)), schema_hook=_schema_hook
                ),
            },
            "patterns": {"runner_ref": REF, "address": ADDRESS, "spec_name": ANY_NAME, "words": WORDS},
            "roles": {str(role): SIGNATURES[role] for role in Role},
            "slots": {str(slot): str(role) for slot, role in ROLES.items()},
            "scopes": [str(scope) for scope in Scope],
            "sections": {str(section): PREFIXES[section] for section in ORDER},
            "tiers": [str(tier) for tier in Tier],
            "budget": {
                "darts_concurrency": self._conf.concurrency,
                "darts_calls": self._conf.calls,
                "darts_fusion_specs": self._conf.fusion_specs,
                "darts_fusion_tokens": self._conf.fusion_tokens,
                "darts_timeout": msgspec.json.encode(self._conf.timeout).decode().strip('"'),
            },
            "laws": [{"rule": str(rule), "scope": scope, "fix": fix} for rule, (scope, fix) in LAWS.items()],
        }

    ##### PROBE #####

    async def probe(self, agent: Answers, tiers: Sequence[Tier] = tuple(Tier)) -> dict[str, Any]:
        """Each tier's answer-time in ms for the trivially structured ask, or the error that shows it is not there."""
        probes: dict[str, Any] = {}
        for tier in tiers:
            started = perf_counter()
            try:
                await agent.run("Probe.", PROBE_PROMPT, PROBE_SCHEMA, endpoint=tier)
            except Exception as error:  # noqa: BLE001 — any failure is the answer: the tier is not there
                probes[str(tier)] = f"{type(error).__name__}: {error}"
            else:
                probes[str(tier)] = round((perf_counter() - started) * 1000.0, 1)
        return probes

    ##### EVALUATE #####

    async def evaluate(
        self,
        pipeline: str,
        data: Mapping[str, Any],
        system: State,
        agent: Answers,
        *,
        expectations: Sequence[str] = (),
    ) -> Readout:
        """Probe, then walk the pipeline's sections in order over `data`, and turn the reading into signals.

        `agent` is what the sections answer with: the real one for a live readout, a scripted one when a
        test drives the same loop. A pipeline with no agent specs never reaches it."""
        probes = await self.probe(agent)
        down = {tier: answer for tier, answer in probes.items() if not isinstance(answer, float)}
        match down:
            case dict() if down:
                return Readout(
                    pipeline=pipeline,
                    mode="infra",
                    probe=probes,
                    signals=tuple(
                        Signal(kind="infra", where=tier, observed="no answer", detail=str(answer))
                        for tier, answer in down.items()
                    ),
                )
        ### the system's root, as RunState takes it: a copy of the whole tree, the agent swapped, its own contexts.
        sandbox = State(
            infra=system.infra,
            logic=dataclasses.replace(system.logic, agent=agent),
            instrument=dataclasses.replace(system.instrument, contexts=InstrumentContexts()),
        )
        sandbox.seal()
        state = RunState(sandbox, pipeline=pipeline)
        state.context.update(data)
        runs = [
            (section, await self._orchestrator.run(section, state))
            for section in SpecDiscover(pipeline, specs=self._specs, runners=self._runners).sections()
        ]
        return Readout(
            pipeline=pipeline,
            mode="live",
            probe=probes,
            summaries={str(section): run.summary for section, run in runs},
            signals=self._signals(state, runs, expectations),
        )

    ##### PRIVATE #####

    def _signals(
        self, state: RunState, runs: Sequence[tuple[Section, SectionRun]], expectations: Sequence[str]
    ) -> tuple[Signal, ...]:
        """Everything the reading left wrong, in one ordered tuple: outcomes, audits, expectations."""
        outcomes = (
            Signal(
                kind="spec",
                where=f"{section}/{outcome.spec}",
                observed=str(outcome.status),
                detail=outcome.error or outcome.reason,
            )
            for section, run in runs
            for outcome in run.outcomes
            if str(outcome.status) in LOST | {"rescued"}
        )
        audits = (
            Signal(kind="audit", where=f"audit/{name}", observed="holds=false", detail=str(verdict))
            for name, verdict in dict(state.context.audit).items()
            if isinstance(verdict, dict) and verdict.get("holds") is False
        )
        expects = (signal for ask in expectations for signal in self._expect(state, ask))
        return (*outcomes, *audits, *expects)

    @staticmethod
    def _expect(state: RunState, ask: str) -> list[Signal]:
        """`<section>/<spec>.<dotted.path>==<json>`: read back off the context and compared, exactly."""
        address, _, wanted = ask.partition("==")
        section, _, rest = address.partition("/")
        spec, _, path = rest.partition(".")
        observed = _dig(getattr(state.context, section).get(spec), path)
        match observed is not MISSING and observed == msgspec.json.decode(wanted.encode()):
            case True:
                return []
            case _:
                observed = "missing" if observed is MISSING else str(observed)
                return [Signal(kind="expect", where=address, observed=observed, expected=wanted)]


def _schema_hook(type_: Any) -> dict[str, Any]:
    """The schema mirror of the checked types a spec field may hold: an `output` is an object with an object root."""
    match type_:
        case type() if issubclass(type_, JsonSchema):
            return {"type": "object"}
        case _:
            msg = f"no contract schema for {type_!r}"
            raise TypeError(msg)


def _dig(value: Any, path: str) -> Any:
    """Walk a dotted path through mappings; the first thing that is not there is `MISSING`."""
    for part in [part for part in path.split(".") if part]:
        match value:
            case dict() if part in value:
                value = value[part]
            case _:
                return MISSING
    return value
