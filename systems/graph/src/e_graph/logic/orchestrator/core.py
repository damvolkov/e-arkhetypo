"""logic.orchestrator.core: run one section of a pipeline — its specs as a parallel-sequential graph.

    the specs of a section                       the plan the orchestrator derives from them
    (D deterministic · S semantic)               (steps in sequence · everything in a step at once)

    D lines ───┐                                 step 0 ║ D lines │ D meta │ ┌ S kind  ┐ one fused agent call
    D meta  ───┼──▶ S total ────┐                       ║         │        │ └ S party ┘ (tier medium)
    S kind  ───┘                ├──▶ D audit            ╠══════════════════════════════════════════════
    S party ──────▶ S currency ─┘                step 1 ║ ┌ S total    ┐ one fused agent call
                                                        ║ └ S currency ┘
    D audit ┄┄▶ D recount  (fallback, held)      step 2 ║ D audit ┄┄ fails? ┄┄▶ D recount takes its place

A spec's step is its depth in the `depends` DAG (topological generations, rustworkx): it runs after
every spec it reads and beside every spec that shares its depth. Within a step, each deterministic spec
is its own task; the semantic ones are grouped by tier and fused — one agent call answers them all, each
under its own name, its own schema — split into more calls when the budget (DARTS_FUSION_TOKENS,
DARTS_FUSION_SPECS) is exceeded. Fallbacks are never scheduled: they wait for their parent to fail.

Every spec, deterministic or fused, crosses the same gates, in order:

    inputs ──▶ check ──▶ produce ──────────────────────▶ validate ──▶ write context.<section>[<spec>]
      │          │       D: run(state)                       │
      │          │       S: pre_run ▶ fused call ▶ post_run  │
      ▼          ▼          ▼ (error · timeout)              ▼ (output breaks `output`)
    skipped   blocked     fallback ──▶ rescued (written under the parent's name) · or failed

`skipped`: a dependency delivered nothing. `blocked`: the spec's `check` refused the state — it would
read corrupt data, so it never runs, and its dependents inherit the block. Each outcome is a ledger
line (`SpecOutcome`): status, step, latency, the fallback that rescued it, the fused call and its usage.
The orchestrator only ever runs a catalog `SpecDiscover` judged coherent: a broken section raises its
`CatalogError` before a single spec runs. CPU-bound specs (`bound: cpu`) run in a worker thread with
their own event loop, so the loop never stalls; their deadline abandons the wait, not the thread."""

import asyncio
import time
from contextlib import contextmanager
from dataclasses import dataclass
from itertools import count
from typing import TYPE_CHECKING, Any, Final

import anyio

from core.logger import logger
from core.settings import settings as st
from e_graph.logic.discover import KINDS, RUNNERS, SPECS, SpecDiscover
from e_graph.logic.errors import BlockedError, OrchestratorError
from e_graph.logic.models import Bound, Hook, SectionRun, SemanticSpec, SpecOutcome, SpecStatus
from e_graph.logic.orchestrator.fusion import SpecFusion
from e_graph.logic.orchestrator.plan import DagPlan

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence
    from pathlib import Path

    from core.settings.darts import DartsSettings
    from e_graph.instrument.state import RunState
    from e_graph.logic.models import Catalog, Reply, SectionPlan, Spec, SpecNode, Step, Tier
    from e_graph.models.section import Section

MS_PER_SECOND: Final[float] = 1000.0


@dataclass(frozen=True, slots=True)
class ScopeCore:
    """What one section run shares across its steps: the run's state, the catalog and the discovery that
    loads its runners, the ledger of outcomes so far, the gates bounding what runs at once, the call counter."""

    state: RunState
    discover: SpecDiscover
    catalog: Catalog
    plan: SectionPlan
    ledger: dict[str, SpecOutcome]
    specs: anyio.Semaphore
    calls: anyio.Semaphore
    counter: Iterator[int]


class OrchestratorCore:
    """Runs a pipeline's sections: one discovery per pipeline, built on first use, and one plan per run."""

    __slots__ = ("_conf", "_discovers", "_kinds", "_runners", "_specs")

    def __init__(
        self,
        settings: DartsSettings | None = None,
        *,
        specs: Path = SPECS,
        runners: Path = RUNNERS,
        kinds: tuple[type[Spec], ...] = KINDS,
    ) -> None:
        ### the default is read on call, not at import: the settings singleton stays lazy.
        self._conf = st.darts if settings is None else settings
        self._specs, self._runners, self._kinds = specs, runners, kinds
        self._discovers: dict[str, SpecDiscover] = {}

    ##### PRIVATE — the section #####

    def _run_discover(self, pipeline: str) -> SpecDiscover:
        """The pipeline's discovery: one per pipeline, kept, so each section is judged once."""
        match self._discovers.get(pipeline):
            case None:
                found = self._discovers[pipeline] = SpecDiscover(
                    pipeline, specs=self._specs, runners=self._runners, kinds=self._kinds
                )
                return found
            case kept:
                return kept

    async def _run_steps(self, steps: Sequence[Step], scope: ScopeCore) -> None:
        """Steps in sequence; inside a step, every deterministic spec and every fused call at once."""
        match steps:
            case [step, *rest]:
                async with anyio.create_task_group() as group:
                    _ = [
                        group.start_soon(self._spec_deterministic, name, step.index, scope)
                        for name in step.deterministic
                    ]
                    _ = [
                        group.start_soon(self._fused_step, call.specs, call.tier, step.index, scope)
                        for call in step.fused
                    ]
                await self._run_steps(rest, scope)
            case _:
                return

    ##### PRIVATE — one spec #####

    def _gate_inputs(self, name: str, step: int, scope: ScopeCore) -> SpecOutcome | None:
        """The outcome of a spec whose dependencies did not deliver — blocked if any was blocked — else None."""
        spec = scope.catalog.nodes[name].spec
        missing = [
            (dependency, scope.ledger[dependency].status)
            for dependency in spec.depends
            if not scope.ledger[dependency].status.delivered
        ]
        match missing:
            case []:
                return None
            case _:
                dependency, status = missing[0]
                blocked = any(found is SpecStatus.BLOCKED for _, found in missing)
                return SpecOutcome(
                    spec=name,
                    kind=self._spec_kind(spec),
                    step=step,
                    status=SpecStatus.BLOCKED if blocked else SpecStatus.SKIPPED,
                    reason=f"input {dependency} {status}",
                )

    async def _spec_deterministic(self, name: str, step: int, scope: ScopeCore) -> None:
        """A deterministic spec of a step: gated, then produced under the step's concurrency bound."""
        match self._gate_inputs(name, step, scope):
            case SpecOutcome() as gated:
                scope.ledger[name] = gated
            case _:
                async with scope.specs:
                    scope.ledger[name] = await self._spec_attempt(name, step, scope)

    async def _spec_attempt(self, name: str, step: int, scope: ScopeCore) -> SpecOutcome:
        """One spec produced alone, in its span: succeeded, blocked, or handed to its fallback."""
        node, started = scope.catalog.nodes[name], time.perf_counter()
        telemetry = scope.state.infra.telemetry
        with telemetry.spec(name, scope.catalog.section, self._spec_kind(node.spec), scope.state.id) as span:
            try:
                self._spec_write(scope, name, await self._spec_produce(node, scope))
                outcome = self._spec_outcome(node, step, SpecStatus.SUCCEEDED, started)
            except BlockedError as refused:
                outcome = self._spec_outcome(node, step, SpecStatus.BLOCKED, started, reason=str(refused))
            except Exception as error:  # noqa: BLE001 — any failure of a spec is its fallback's cue, never the run's end
                outcome = await self._spec_rescue(name, step, error, scope, started)
            telemetry.settle(span, outcome)
        return outcome

    async def _spec_produce(self, node: SpecNode, scope: ScopeCore) -> dict[str, Any]:
        """A spec's output, alone, within its deadline: its check, then its run — or its own one-spec call."""
        await self._spec_check(node, scope)
        with self._common_deadline(self._spec_timeout(node), node.spec.name):
            match node.spec:
                case SemanticSpec(tier=tier):
                    name = node.spec.name
                    material = {name: await self._spec_material(node, scope)}
                    reply = await self._fused_ask([node], tier, material, scope)
                    return await self._spec_finish(node, SpecFusion.split(reply.output, [name])[name], scope)
                case _:
                    return self._spec_validate(node, await self._spec_call(node, Hook.RUN, scope))

    async def _spec_check(self, node: SpecNode, scope: ScopeCore) -> None:
        """The spec's integrity gate: its `check` must return True for the spec to read the state at all."""
        match node.hooks.get(Hook.CHECK):
            case None:
                return
            case _:
                match await self._spec_call(node, Hook.CHECK, scope):
                    case True:
                        return
                    case refused:
                        msg = f"{node.spec.name}: check refused the state ({refused!r})"
                        raise BlockedError(msg)

    async def _spec_material(self, node: SpecNode, scope: ScopeCore) -> str:
        """What a semantic spec's `pre_run` prepared for the prompt; nothing without one."""
        match node.hooks.get(Hook.PRE):
            case None:
                return ""
            case _:
                return str(await self._spec_call(node, Hook.PRE, scope))

    async def _spec_finish(self, node: SpecNode, answer: Any, scope: ScopeCore) -> dict[str, Any]:
        """A semantic spec's answer, reshaped by its `post_run` if it has one, then held to its `output`."""
        match node.hooks.get(Hook.POST):
            case None:
                return self._spec_validate(node, answer)
            case _:
                return self._spec_validate(node, await self._spec_call(node, Hook.POST, scope, answer))

    async def _spec_call(self, node: SpecNode, hook: Hook, scope: ScopeCore, *args: Any) -> Any:
        """One of the spec's hooks on the run's state: on the loop, or — `bound: cpu` — on a thread's own loop."""
        function = await scope.discover.load(node.hooks[hook])
        match node.spec.bound:
            case Bound.CPU:
                ### abandon_on_cancel: a deadline stops the wait at once; the thread finishes on its own.
                return await anyio.to_thread.run_sync(asyncio.run, function(scope.state, *args), abandon_on_cancel=True)
            case _:
                return await function(scope.state, *args)

    async def _spec_rescue(
        self, name: str, step: int, error: BaseException, scope: ScopeCore, started: float
    ) -> SpecOutcome:
        """A failed spec's last chance: its fallback produces in its place, written under its name — or it failed."""
        node = scope.catalog.nodes[name]
        failure = f"{type(error).__name__}: {error}"
        match scope.plan.fallbacks.get(name):
            case None:
                return self._spec_outcome(node, step, SpecStatus.FAILED, started, error=failure)
            case rescuer:
                try:
                    self._spec_write(scope, name, await self._spec_produce(scope.catalog.nodes[rescuer], scope))
                except Exception as second:  # noqa: BLE001 — the fallback failing too is the spec failing, both reasons kept
                    lost = f"{failure}; fallback {rescuer}: {type(second).__name__}: {second}"
                    return self._spec_outcome(node, step, SpecStatus.FAILED, started, error=lost, rescuer=rescuer)
                return self._spec_outcome(node, step, SpecStatus.RESCUED, started, reason=failure, rescuer=rescuer)

    @staticmethod
    def _spec_validate(node: SpecNode, output: Any) -> dict[str, Any]:
        """The output held to the spec's `output` schema, compiled once (jsonschema-rs); a breach raises."""
        node.spec.output.validator.validate(output)
        return output

    @staticmethod
    def _spec_write(scope: ScopeCore, name: str, output: dict[str, Any]) -> None:
        """The output where every later reader finds it: `state.context.<section>[<spec>]`."""
        getattr(scope.state.context, scope.catalog.section)[name] = output

    @staticmethod
    @contextmanager
    def _common_deadline(seconds: float, what: str) -> Iterator[None]:
        """A deadline that says, when it passes, whose it was and how long it gave."""
        try:
            with anyio.fail_after(seconds):
                yield
        except TimeoutError as passed:
            msg = f"{what} passed its deadline of {seconds:.1f}s"
            raise TimeoutError(msg) from passed

    def _spec_timeout(self, node: SpecNode) -> float:
        timeout = node.spec.timeout or self._conf.darts_timeout
        return timeout.total_seconds()

    @staticmethod
    def _spec_kind(spec: Spec[str]) -> str:
        return str(spec.__struct_config__.tag)

    @staticmethod
    def _spec_outcome(node: SpecNode, step: int, status: SpecStatus, started: float, **details: Any) -> SpecOutcome:
        latency = (time.perf_counter() - started) * MS_PER_SECOND
        return SpecOutcome(
            spec=node.spec.name,
            kind=OrchestratorCore._spec_kind(node.spec),
            step=step,
            status=status,
            latency_ms=latency,
            **details,
        )

    ##### PRIVATE — fused calls #####

    async def _fused_step(self, names: Sequence[str], tier: Tier, step: int, scope: ScopeCore) -> None:
        """A step's semantic specs of one tier: gated, checked, their material prepared, then packed into calls
        by what they really weigh — material included — and sent at once, within the calls bound."""
        gated = {name: outcome for name in names if (outcome := self._gate_inputs(name, step, scope)) is not None}
        scope.ledger.update(gated)
        prepared = {name: await self._fused_prepare(name, step, scope) for name in names if name not in gated}
        scope.ledger.update({name: value for name, value in prepared.items() if isinstance(value, SpecOutcome)})
        material = {name: value for name, value in prepared.items() if isinstance(value, str)}
        nodes, wiki = scope.catalog.nodes, scope.catalog.wiki
        weights = {name: SpecFusion.weight(nodes[name], wiki, text) for name, text in material.items()}
        groups = SpecFusion.pack(weights, budget=self._conf.darts_fusion_tokens, most=self._conf.darts_fusion_specs)
        async with anyio.create_task_group() as group:
            _ = [group.start_soon(self._fused_send, specs, tier, step, material, scope) for specs in groups]

    async def _fused_prepare(self, name: str, step: int, scope: ScopeCore) -> str | SpecOutcome:
        """A semantic spec ready for its call: checked, its material prepared — or already ended (blocked, rescued, failed)."""
        node, started = scope.catalog.nodes[name], time.perf_counter()
        try:
            await self._spec_check(node, scope)
            return await self._spec_material(node, scope)
        except BlockedError as refused:
            return self._spec_outcome(node, step, SpecStatus.BLOCKED, started, reason=str(refused))
        except Exception as error:  # noqa: BLE001 — a spec that cannot prepare leaves the call, to its fallback
            return await self._spec_rescue(name, step, error, scope, started)

    async def _fused_send(
        self, names: Sequence[str], tier: Tier, step: int, material: Mapping[str, str], scope: ScopeCore
    ) -> None:
        """One fused call, in its span: every spec it answers finished on its own; a failed call hands each to its fallback."""
        nodes, started = scope.catalog.nodes, time.perf_counter()
        telemetry = scope.state.infra.telemetry
        async with scope.calls:
            index = next(scope.counter)
            with telemetry.spec(f"call-{index}", scope.catalog.section, "fused", scope.state.id) as span:
                try:
                    with self._common_deadline(max(self._spec_timeout(nodes[name]) for name in names), f"call-{index}"):
                        reply = await self._fused_ask(
                            [nodes[name] for name in names], tier, {name: material[name] for name in names}, scope
                        )
                except Exception as error:  # noqa: BLE001 — a failed call is each of its specs' fallback cue
                    outcomes = {name: await self._spec_rescue(name, step, error, scope, started) for name in names}
                else:
                    answers = SpecFusion.split(reply.output, names)
                    outcomes = {
                        name: await self._fused_finish(
                            name, answers[name], reply=reply, index=index, step=step, scope=scope, started=started
                        )
                        for name in names
                    }
                span.record(
                    {
                        "spec.specs": ", ".join(names),
                        "spec.tier": str(tier),
                        "spec.statuses": ", ".join(f"{name}={outcome.status}" for name, outcome in outcomes.items()),
                    }
                )
        scope.ledger.update(outcomes)

    async def _fused_ask(
        self, nodes: Sequence[SpecNode], tier: Tier, material: Mapping[str, str], scope: ScopeCore
    ) -> Reply[dict[str, Any]]:
        """The agent asked once for every spec: fused instructions, fused prompt, fused schema, at the specs' tier."""
        wiki = scope.catalog.wiki
        return await scope.state.infra.agent.run(
            SpecFusion.instructions(nodes, wiki), SpecFusion.prompt(material), SpecFusion.schema(nodes), endpoint=tier
        )

    async def _fused_finish(
        self,
        name: str,
        answer: Any,
        *,
        reply: Reply[dict[str, Any]],
        index: int,
        step: int,
        scope: ScopeCore,
        started: float,
    ) -> SpecOutcome:
        """One spec's part of a fused reply: post_run, validated, written — or its fallback's turn."""
        node = scope.catalog.nodes[name]
        try:
            self._spec_write(scope, name, await self._spec_finish(node, answer, scope))
        except Exception as error:  # noqa: BLE001 — a part that breaks its own schema is that spec's failure alone
            return await self._spec_rescue(name, step, error, scope, started)
        return self._spec_outcome(node, step, SpecStatus.SUCCEEDED, started, call=index, usage=reply.usage)

    ############################################################

    ##### PUBLIC #####

    async def plan(self, pipeline: str, section: Section) -> SectionPlan:
        """How a pipeline's section would run — its steps and fused calls — without running anything."""
        return DagPlan.build(await self._run_discover(pipeline).catalog(section), self._conf)

    async def run(self, section: Section, state: RunState) -> SectionRun:
        """Run a section of the state's pipeline: every spec in its step, the outcomes in plan order."""
        match state.pipeline:
            case "":
                msg = "the run names no pipeline: the orchestrator cannot tell whose specs to run"
                raise OrchestratorError(msg)
            case pipeline:
                discover = self._run_discover(pipeline)
        started = time.perf_counter()
        catalog = await discover.catalog(section)
        plan = DagPlan.build(catalog, self._conf)
        scope = ScopeCore(
            state=state,
            discover=discover,
            catalog=catalog,
            plan=plan,
            ledger={},
            specs=anyio.Semaphore(self._conf.darts_concurrency),
            calls=anyio.Semaphore(self._conf.darts_calls),
            counter=count(),
        )
        await self._run_steps(plan.steps, scope)
        run = SectionRun(
            pipeline=pipeline,
            section=section,
            plan=plan,
            outcomes=tuple(scope.ledger[name] for step in plan.steps for name in step.specs),
            latency_ms=(time.perf_counter() - started) * MS_PER_SECOND,
        )
        logger.info("section run", pipeline=pipeline, section=section, summary=run.summary, step="DARTS")
        return run
