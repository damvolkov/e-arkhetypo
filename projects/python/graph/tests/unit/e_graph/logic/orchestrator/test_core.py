"""tests/unit: logic.orchestrator.core — a section run end to end: steps, gates, fusion, fallbacks, bounds, spans.

Specs and runners are written to disk and loaded as in production; the agent is scripted. Every gate of
the lifecycle drawn in core.py is crossed on purpose: inputs, check, produce, validate, write, fallback."""

import threading
from datetime import timedelta
from typing import TYPE_CHECKING

import anyio
import pytest

from e_graph.logic.errors import CatalogError, OrchestratorError, SectionError
from e_graph.logic.models import Role, SpecStatus
from support.darts import SECTION, USAGE

if TYPE_CHECKING:
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from e_graph.logic.models import SectionRun
    from support.darts import DartsHarness

NUMBER = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}
TOTAL = {"type": "object", "properties": {"total": {"type": "number"}, "post": {"type": "boolean"}}}
FLIGHT = """\
state.context["flight"] = state.context.get("flight", 0) + 1
state.context["peak"] = max(state.context.get("peak", 0), state.context["flight"])
await asyncio.sleep(0.02)
state.context["flight"] -= 1
return {}"""


def statuses(run: SectionRun) -> dict[str, SpecStatus]:
    return {outcome.spec: outcome.status for outcome in run.outcomes}


def outcome(run: SectionRun, name: str):
    return next(item for item in run.outcomes if item.spec == name)


##### THE DIAGRAM #####
async def test_the_diagram_runs_step_by_step(darts: DartsHarness) -> None:
    darts.diagram()
    run, state = await darts.run()
    assert run.summary == "7 specs in 3 steps: 7 succeeded"
    assert [item.spec for item in run.outcomes] == [
        "EXT-lines", "EXT-meta", "EXT-kind", "EXT-party", "EXT-currency", "EXT-total", "EXT-audit",
    ]  # fmt: skip
    assert [item.step for item in run.outcomes] == [0, 0, 0, 0, 1, 1, 2]
    ### one fused call per step and tier: the two semantic pairs, in step order.
    assert [call["specs"] for call in darts.agent.calls] == [("EXT-kind", "EXT-party"), ("EXT-currency", "EXT-total")]
    assert set(darts.written(state)) == {item.spec for item in run.outcomes}
    fused = [item for item in run.outcomes if item.kind == "semantic"]
    assert {(item.call, item.usage) for item in fused} == {(0, USAGE), (1, USAGE)}
    assert {item.usage for item in run.outcomes if item.kind == "deterministic"} == {None}
    assert run.latency_ms > 0


async def test_downstream_specs_read_what_upstream_wrote(darts: DartsHarness) -> None:
    darts.deterministic("EXT-a", output=NUMBER)
    darts.runner("EXT-a", run='return {"n": 2}')
    darts.deterministic("EXT-b", output=NUMBER, depends=("EXT-a",))
    darts.runner("EXT-b", run='return {"n": state.context.extract["EXT-a"]["n"] * 10}')
    _, state = await darts.run()
    assert darts.written(state) == {"EXT-a": {"n": 2}, "EXT-b": {"n": 20}}


async def test_a_runner_reads_its_call(darts: DartsHarness) -> None:
    darts.deterministic("EXT-a", output=NUMBER)
    darts.runner("EXT-a", run='return {"n": 2}')
    darts.deterministic("EXT-b", depends=("EXT-a",))
    darts.runner(
        "EXT-b", run='return {"seen": [call.pipeline, call.section, call.spec, call.slot, call.inputs, call.args]}'
    )
    _, state = await darts.run()
    assert darts.written(state)["EXT-b"] == {"seen": ["doc", "extract", "EXT-b", "runner", {"EXT-a": {"n": 2}}, {}]}


async def test_a_runner_takes_its_args_validated(darts: DartsHarness) -> None:
    darts.deterministic("EXT-a", output=NUMBER, args={"runner": {"factor": 3}})
    darts.crafter.write_runner(
        SECTION, "a", Role.RUN, args="    factor: int\n", body='return {"n": call.args.factor * 2}'
    )
    run, state = await darts.run()
    assert (run.summary, darts.written(state)) == ("1 specs in 1 steps: 1 succeeded", {"EXT-a": {"n": 6}})


##### GATES #####
async def test_a_refused_check_blocks_the_spec_and_everything_downstream(darts: DartsHarness) -> None:
    darts.deterministic("EXT-a")
    darts.runner("EXT-a", run="return {}", check="return False")
    darts.deterministic("EXT-b", depends=("EXT-a",))
    darts.runner("EXT-b", run="return {}")
    darts.semantic("EXT-c", depends=("EXT-b",))
    run, state = await darts.run()
    assert statuses(run) == {"EXT-a": SpecStatus.BLOCKED, "EXT-b": SpecStatus.BLOCKED, "EXT-c": SpecStatus.BLOCKED}
    assert "check refused the state" in outcome(run, "EXT-a").reason
    assert (outcome(run, "EXT-b").reason, outcome(run, "EXT-c").reason) == (
        "input EXT-a blocked",
        "input EXT-b blocked",
    )
    assert (darts.written(state), darts.agent.calls) == ({}, [])


async def test_a_passing_check_lets_the_spec_read_the_state(darts: DartsHarness) -> None:
    darts.deterministic("EXT-a", output=NUMBER)
    darts.runner("EXT-a", run='return {"n": 1}', check='return "pages" in state.context')
    state = darts.state()
    state.context.pages = ["cover", "statement"]
    run = await darts.orchestrator.run(SECTION, state)
    assert (outcome(run, "EXT-a").status, darts.written(state)) == (SpecStatus.SUCCEEDED, {"EXT-a": {"n": 1}})


async def test_a_failure_skips_its_dependents(darts: DartsHarness) -> None:
    darts.deterministic("EXT-a")
    darts.runner("EXT-a", run='raise RuntimeError("boom")')
    darts.deterministic("EXT-b", depends=("EXT-a",))
    darts.runner("EXT-b", run="return {}")
    run, _ = await darts.run()
    assert statuses(run) == {"EXT-a": SpecStatus.FAILED, "EXT-b": SpecStatus.SKIPPED}
    assert (outcome(run, "EXT-a").error, outcome(run, "EXT-b").reason) == ("RuntimeError: boom", "input EXT-a failed")


@pytest.mark.parametrize(
    ("body", "fields", "error"),
    [
        ('return {"n": "x"}', {}, "ValidationError"),
        ("return 7", {}, "ValidationError"),
        (
            "await asyncio.sleep(2)\nreturn {}",
            {"timeout": timedelta(milliseconds=50)},
            "TimeoutError: EXT-a passed its deadline of 0.1s",
        ),
    ],
    ids=["output-breaks-schema", "output-not-an-object", "past-its-timeout"],
)
async def test_an_output_that_cannot_stand_fails_the_spec(
    darts: DartsHarness, body: str, fields: dict[str, object], error: str
) -> None:
    darts.deterministic("EXT-a", output=NUMBER, **fields)
    darts.runner("EXT-a", imports="import asyncio", run=body)
    run, state = await darts.run()
    assert outcome(run, "EXT-a").status is SpecStatus.FAILED
    assert outcome(run, "EXT-a").error.startswith(error)
    assert darts.written(state) == {}


##### FALLBACKS #####
async def test_a_fallback_rescues_its_parent_in_its_place(darts: DartsHarness) -> None:
    darts.deterministic("EXT-a", output=NUMBER, fallback="EXT-f")
    darts.runner("EXT-a", run="return {}", check='raise ValueError("unreadable state")')
    darts.deterministic("EXT-f", output=NUMBER)
    darts.runner("EXT-f", run='return {"n": 7}')
    darts.deterministic("EXT-b", output=NUMBER, depends=("EXT-a",))
    darts.runner("EXT-b", run='return {"n": state.context.extract["EXT-a"]["n"] + 1}')
    run, state = await darts.run()
    rescued = outcome(run, "EXT-a")
    assert (rescued.status, rescued.rescuer, rescued.reason) == (
        SpecStatus.RESCUED,
        "EXT-f",
        "ValueError: unreadable state",
    )
    ### written under the parent's name: its dependents never know a fallback answered.
    assert darts.written(state) == {"EXT-a": {"n": 7}, "EXT-b": {"n": 8}}
    assert "EXT-f" not in statuses(run)


async def test_a_failed_fallback_fails_its_parent_with_both_reasons(darts: DartsHarness) -> None:
    darts.deterministic("EXT-a", fallback="EXT-f")
    darts.runner("EXT-a", run='raise RuntimeError("first")')
    darts.deterministic("EXT-f")
    darts.runner("EXT-f", run="return {}", check="return False")
    run, _ = await darts.run()
    failed = outcome(run, "EXT-a")
    assert (failed.status, failed.rescuer) == (SpecStatus.FAILED, "EXT-f")
    assert failed.error.startswith("RuntimeError: first; fallback EXT-f: BlockedError: EXT-f: check refused")


async def test_a_semantic_fallback_answers_alone(darts: DartsHarness) -> None:
    darts.deterministic("EXT-a", output=TOTAL, fallback="EXT-s")
    darts.runner("EXT-a", run='raise RuntimeError("parser broke")')
    darts.semantic("EXT-s", output=TOTAL)
    darts.agent.answers["EXT-s"] = {"total": 416161}
    run, state = await darts.run()
    assert (outcome(run, "EXT-a").status, outcome(run, "EXT-a").rescuer) == (SpecStatus.RESCUED, "EXT-s")
    assert [call["specs"] for call in darts.agent.calls] == [("EXT-s",)]
    assert darts.written(state) == {"EXT-a": {"total": 416161}}


##### FUSION #####
async def test_material_and_post_run_frame_the_fused_answer(darts: DartsHarness) -> None:
    darts.semantic("EXT-a", output=TOTAL)
    darts.runner("EXT-a", pre_run='return "page 44 says 416,161"', post_run='return {**output, "post": True}')
    darts.semantic("EXT-b", output=TOTAL)
    darts.agent.answers["EXT-a"] = {"total": 416161}
    run, state = await darts.run()
    (call,) = darts.agent.calls
    assert call["specs"] == ("EXT-a", "EXT-b")
    assert "### Material for EXT-a\npage 44 says 416,161" in call["prompt"]
    assert call["schema"]["required"] == ["EXT-a", "EXT-b"]
    assert darts.written(state) == {"EXT-a": {"total": 416161, "post": True}, "EXT-b": {}}
    assert set(statuses(run).values()) == {SpecStatus.SUCCEEDED}


async def test_a_part_that_breaks_its_schema_fails_only_its_spec(darts: DartsHarness) -> None:
    darts.semantic("EXT-a", output=TOTAL)
    darts.semantic("EXT-b", output=TOTAL)
    darts.agent.answers["EXT-b"] = {"total": "lots"}
    run, state = await darts.run()
    assert statuses(run) == {"EXT-a": SpecStatus.SUCCEEDED, "EXT-b": SpecStatus.FAILED}
    assert outcome(run, "EXT-b").error.startswith("ValidationError")
    assert set(darts.written(state)) == {"EXT-a"}


async def test_a_failed_call_hands_each_spec_to_its_fallback(darts: DartsHarness) -> None:
    darts.semantic("EXT-a", fallback="EXT-f")
    darts.semantic("EXT-b")
    darts.semantic("EXT-c", tier="high")
    darts.deterministic("EXT-f")
    darts.runner("EXT-f", run='return {"by": "fallback"}')
    darts.agent.down.add("EXT-a")
    run, state = await darts.run()
    assert statuses(run) == {"EXT-c": SpecStatus.SUCCEEDED, "EXT-a": SpecStatus.RESCUED, "EXT-b": SpecStatus.FAILED}
    assert outcome(run, "EXT-b").error == "ProviderError: provider down for ['EXT-a']"
    assert darts.written(state) == {"EXT-a": {"by": "fallback"}, "EXT-c": {}}


async def test_a_spec_that_cannot_prepare_leaves_the_call(darts: DartsHarness) -> None:
    darts.semantic("EXT-a")
    darts.runner("EXT-a", pre_run='raise KeyError("pages")')
    darts.semantic("EXT-b")
    darts.runner("EXT-b", check="return False")
    darts.semantic("EXT-c")
    run, _ = await darts.run()
    assert statuses(run) == {"EXT-a": SpecStatus.FAILED, "EXT-b": SpecStatus.BLOCKED, "EXT-c": SpecStatus.SUCCEEDED}
    assert [call["specs"] for call in darts.agent.calls] == [("EXT-c",)]


async def test_material_heavier_than_the_budget_splits_the_call(darts: DartsHarness) -> None:
    darts.configure(fusion_tokens=600)
    darts.semantic("EXT-a")
    darts.runner("EXT-a", pre_run='return "row " * 400')
    darts.semantic("EXT-b")
    darts.runner("EXT-b", pre_run='return "cell " * 400')
    (step,) = (await darts.orchestrator.plan("doc", SECTION)).steps
    assert [call.specs for call in step.fused] == [("EXT-a", "EXT-b")]
    run, _ = await darts.run()
    assert sorted(call["specs"] for call in darts.agent.calls) == [("EXT-a",), ("EXT-b",)]
    assert {outcome(run, name).call for name in ("EXT-a", "EXT-b")} == {0, 1}


##### BOUNDS #####
@pytest.mark.parametrize(("limit", "peak"), [(1, 1), (2, 2), (8, 4)])
async def test_a_step_runs_at_most_its_concurrency_at_once(darts: DartsHarness, limit: int, peak: int) -> None:
    darts.configure(concurrency=limit)
    for name in ("EXT-a", "EXT-b", "EXT-c", "EXT-d"):
        darts.deterministic(name)
        darts.runner(name, imports="import asyncio", run=FLIGHT)
    _, state = await darts.run()
    assert state.context["peak"] == peak


async def test_cpu_bound_specs_run_off_the_loop(darts: DartsHarness) -> None:
    thread = {"type": "object", "properties": {"thread": {"type": "integer"}}}
    darts.deterministic("EXT-io", output=thread)
    darts.runner("EXT-io", imports="import threading", run='return {"thread": threading.get_ident()}')
    darts.deterministic("EXT-cpu", output=thread, bound="cpu")
    darts.runner("EXT-cpu", imports="import threading", run='return {"thread": threading.get_ident()}')
    _, state = await darts.run()
    written = darts.written(state)
    assert written["EXT-io"]["thread"] == threading.get_ident()
    assert written["EXT-cpu"]["thread"] != threading.get_ident()


##### THE RUN #####
async def test_a_run_without_a_pipeline_is_refused(darts: DartsHarness) -> None:
    with pytest.raises(OrchestratorError, match="names no pipeline"):
        await darts.orchestrator.run(SECTION, darts.state(pipeline=""))


async def test_an_incoherent_section_never_runs(darts: DartsHarness) -> None:
    darts.deterministic("EXT-a")
    darts.runner("EXT-a", imports="import pathlib", run='pathlib.Path("ran").touch()\nreturn {}')
    darts.deterministic("EXT-b", depends=("EXT-ghost-1",))
    with pytest.raises(CatalogError):
        await darts.run()
    assert not await anyio.Path("ran").exists()


async def test_an_empty_section_runs_nothing(darts: DartsHarness) -> None:
    run, _ = await darts.run()
    assert (run.outcomes, run.summary) == ((), "0 specs in 0 steps: nothing to run")


async def test_every_spec_and_call_leaves_its_span(darts: DartsHarness, exporter: InMemorySpanExporter) -> None:
    darts.diagram()
    darts.runner("EXT-lines", run='raise RuntimeError("boom")')
    await darts.run()
    spans = {span.name: span for span in exporter.get_finished_spans()}
    assert {"spec.EXT-lines", "spec.EXT-meta", "spec.call-0"} <= set(spans)
    lines = dict(spans["spec.EXT-lines"].attributes or {})
    assert (lines["spec.status"], lines["spec.section"], lines["spec.kind"]) == ("failed", "extract", "deterministic")
    assert dict(spans["spec.call-0"].attributes or {})["spec.statuses"] == "EXT-kind=succeeded, EXT-party=succeeded"


##### THE NODE #####
async def test_a_strict_node_fails_naming_every_lost_spec(darts: DartsHarness) -> None:
    darts.deterministic("EXT-a")
    darts.runner("EXT-a", run='raise RuntimeError("boom")')
    darts.deterministic("EXT-b")
    darts.runner("EXT-b", run="return {}", check="return False")
    darts.deterministic("EXT-c")
    darts.runner("EXT-c", run="return {}")
    with pytest.raises(SectionError) as caught:
        await darts.orchestrator.node(SECTION, darts.state())
    assert str(caught.value) == (
        "EXT-a failed: RuntimeError: boom; EXT-b blocked: EXT-b: check refused the state (False)"
    )


async def test_a_lenient_node_reports_what_was_delivered(darts: DartsHarness) -> None:
    darts.deterministic("EXT-a")
    darts.runner("EXT-a", run='raise RuntimeError("boom")')
    darts.deterministic("EXT-c")
    darts.runner("EXT-c", run="return {}")
    report = await darts.orchestrator.node(SECTION, darts.state(), strict=False)
    assert report == {
        "summary": "2 specs in 1 steps: 1 succeeded, 1 failed",
        "specs": {"EXT-a": "failed", "EXT-c": "succeeded"},
    }


async def test_every_agent_call_is_kept_whole_as_sent(darts: DartsHarness, exporter: InMemorySpanExporter) -> None:
    darts.semantic("EXT-a", output=TOTAL)
    darts.runner("EXT-a", pre_run='return "page 44 says 416,161"')
    darts.semantic("EXT-b", output=TOTAL)
    darts.deterministic("EXT-c", fallback="EXT-s")
    darts.runner("EXT-c", run='raise RuntimeError("parser broke")')
    darts.semantic("EXT-s")
    run, _ = await darts.run()
    fused, alone = sorted(run.calls, key=lambda call: len(call.specs), reverse=True)
    sent = {call["specs"]: call for call in darts.agent.calls}
    assert (fused.specs, fused.step, fused.tier, fused.budget) == (("EXT-a", "EXT-b"), 0, "medium", 8000)
    assert (fused.prompt, fused.instructions, fused.schema) == (
        sent[fused.specs]["prompt"],
        sent[fused.specs]["instructions"],
        sent[fused.specs]["schema"],
    )
    assert fused.weights["EXT-a"] > fused.weights["EXT-b"]
    assert alone.specs == ("EXT-s",)
    assert sorted(call.index for call in run.calls) == [0, 1]
    spans = {span.name: dict(span.attributes or {}) for span in exporter.get_finished_spans()}
    call = spans[f"spec.call-{fused.index}"]
    assert (call["input.value"], call["spec.instructions"]) == (fused.prompt, fused.instructions)
