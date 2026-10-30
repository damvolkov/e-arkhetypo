"""tests/unit: logic.dartsops — the contract mirrors the laws, the probe times tiers, the readout hears every signal."""

from types import MappingProxyType
from typing import TYPE_CHECKING, Any

import pytest

from e_graph.instrument.contexts import InstrumentContexts
from e_graph.instrument.state import InfraState, InstrumentState
from e_graph.instrument.telemetry import InstrumentTelemetry
from e_graph.logic import dartsops
from e_graph.logic.dartsops import MISSING, DartsOps, _dig
from e_graph.logic.errors import Rule
from e_graph.logic.models import DeterministicSpec, JsonSchema, Reply, Role, Section, SemanticSpec, Tier
from e_graph.logic.orchestrator.core import OrchestratorCore
from e_graph.logic.state import LogicState
from infra.settings import settings as st
from infra.state import State

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from pytest_resources import Resources

    from support.darts import DartsHarness

from infra.config.otel import OtelSettings
from providers.drivers.otel import OtelDriver
from support.crafter import SpecCrafter
from support.darts import DartsHarness

Y_SCHEMA: dict[str, Any] = {"type": "object", "properties": {"y": {"type": "number"}}, "required": ["y"], "additionalProperties": False}  # fmt: skip
HOLDS: dict[str, Any] = {"type": "object", "properties": {"holds": {"type": "boolean"}}, "required": ["holds"], "additionalProperties": False}  # fmt: skip


@pytest.fixture
async def darts(resources: Resources, tmp_path: Path, exporter: InMemorySpanExporter) -> AsyncIterator[DartsHarness]:
    async with OtelDriver(OtelSettings(), exporter) as telemetry:
        yield DartsHarness(SpecCrafter(resources, tmp_path, seed=7), telemetry)


class DownHigh:
    """A tier set where HIGH does not answer: probe must name it, not time it."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    async def run(self, instructions: str, prompt: str, output: Any, *, endpoint: Any = None, **_: Any) -> Reply[Any]:
        match endpoint:
            case Tier.HIGH:
                msg = "high is asleep"
                raise ConnectionError(msg)
            case _:
                return await self._inner.run(instructions, prompt, output, endpoint=endpoint)


def ops_of(harness: DartsHarness) -> DartsOps:
    return DartsOps(harness.orchestrator, specs=harness.crafter.specs, runners=harness.crafter.runners)


def tree_of(harness: DartsHarness, agent: Any) -> State:
    root = State(
        infra=InfraState(
            providers=None,  # ty: ignore[invalid-argument-type]
            engines=None,  # ty: ignore[invalid-argument-type]
            processors=None,  # ty: ignore[invalid-argument-type]
            graphs=MappingProxyType({}),
        ),
        logic=LogicState(agent=agent, orchestrator=harness.orchestrator),
        instrument=InstrumentState(telemetry=InstrumentTelemetry(), contexts=InstrumentContexts()),
    )
    root.seal()
    return root


##### CONTRACT #####
def test_the_contract_mirrors_grammar_laws_and_budgets() -> None:
    contract = DartsOps(OrchestratorCore()).contract()
    assert sorted(contract) == ["budget", "kinds", "laws", "patterns", "roles", "scopes", "sections", "slots", "tiers"]
    assert {law["rule"] for law in contract["laws"]} == {str(rule) for rule in Rule}
    assert all(law["fix"] and law["scope"] for law in contract["laws"])
    assert (contract["sections"]["extract"], contract["sections"]["report"]) == ("EXT", "REP")
    assert set(contract["roles"]) == {"run", "check", "pre_run", "post_run"}
    assert contract["slots"] == {"runner": "run", "check": "check", "pre": "pre_run", "post": "post_run"}
    assert contract["budget"]["darts_fusion_specs"] == st.darts.darts_fusion_specs
    assert contract["budget"]["darts_timeout"].startswith("PT")


def test_the_contract_is_the_same_mirror_twice() -> None:
    ops = DartsOps(OrchestratorCore())
    assert ops.contract() == ops.contract()


def test_the_kinds_carry_their_slots() -> None:
    defs = DartsOps(OrchestratorCore()).contract()["kinds"]["semantic"]["$defs"]
    fields = next(value["properties"] for value in defs.values() if value.get("title", "").startswith("SemanticSpec"))
    assert {"pre", "post", "check", "instructions", "tier"} <= set(fields)


def test_the_schema_hook_refuses_types_the_mirror_cannot_hold() -> None:
    with pytest.raises(TypeError, match="no contract schema"):
        dartsops._schema_hook(dict)
    assert dartsops._schema_hook(JsonSchema) == {"type": "object"}


##### PROBE #####
async def test_the_probe_times_every_tier_that_answers(darts: DartsHarness) -> None:
    probes = await ops_of(darts).probe(darts.agent)
    assert set(probes) == {"high", "medium", "low"}
    assert all(isinstance(ms, float) and ms >= 0.0 for ms in probes.values())


async def test_a_down_tier_comes_back_as_its_error_not_a_time(darts: DartsHarness) -> None:
    probes = await ops_of(darts).probe(DownHigh(darts.agent))
    assert probes["high"].startswith("ConnectionError:")
    assert isinstance(probes["medium"], float)


##### READOUT #####
async def test_a_green_tree_walks_to_a_green_readout(darts: DartsHarness) -> None:
    darts.deterministic(
        "EXT-lines",
        output={
            "type": "object",
            "properties": {"x": {"type": "number"}},
            "required": ["x"],
            "additionalProperties": False,
        },
    )
    darts.runner("EXT-lines", run='return {"x": 1}')
    darts.semantic("EXT-kind", output=Y_SCHEMA)
    darts.agent.answers["EXT-kind"] = {"y": 2}
    readout = await ops_of(darts).evaluate(
        "doc", {}, tree_of(darts, darts.agent), darts.agent, expectations=["extract/EXT-lines.x==1", "extract/EXT-kind.y==2"]
    )  # fmt: skip
    assert (readout.ok, readout.mode, readout.pipeline) == (True, "live", "doc")
    assert list(readout.summaries) == ["extract"]
    assert readout.signals == ()


async def test_every_wrong_the_system_knows_becomes_a_signal(darts: DartsHarness) -> None:
    darts.deterministic("EXT-lost")
    darts.runner("EXT-lost", run="raise ValueError('no output')")
    darts.deterministic("EXT-covered", output=Y_SCHEMA, fallback="EXT-covered-read")
    darts.runner("EXT-covered", run="raise ValueError('regex missed')")
    darts.crafter.write_spec(
        Section.EXTRACT,
        SemanticSpec(
            name="EXT-covered-read",
            description="the semantic reading.",
            output=JsonSchema(Y_SCHEMA),
            instructions="Read the identifier off the page.",
        ),
    )
    darts.crafter.write_spec(
        Section.AUDIT,
        DeterministicSpec(name="AUD-x", description="an audit.", output=JsonSchema(HOLDS), runner="owned/x"),
    )
    darts.crafter.write_runner(Section.AUDIT, "x", Role.RUN, body='return {"holds": False}', doc="audit run.")
    darts.agent.answers["EXT-covered-read"] = {"y": 7}
    readout = await ops_of(darts).evaluate(
        "doc",
        {},
        tree_of(darts, darts.agent),
        darts.agent,
        expectations=["extract/EXT-lost.nope==1"],
    )
    heard = {(signal.kind, signal.where) for signal in readout.signals}
    assert ("spec", "extract/EXT-lost") in heard
    assert ("spec", "extract/EXT-covered") in heard  # rescued is drift: the deterministic needs repair
    assert ("audit", "audit/AUD-x") in heard
    assert ("expect", "extract/EXT-lost.nope") in heard
    assert "extract/EXT-covered.y==7" not in [signal.where for signal in readout.signals if signal.kind == "expect"]


async def test_an_unreachable_tier_is_infra_alone_and_stops_the_walk(darts: DartsHarness) -> None:
    readout = await ops_of(darts).evaluate("doc", {}, tree_of(darts, DownHigh(darts.agent)), DownHigh(darts.agent))
    assert readout.mode == "infra"
    assert [signal.kind for signal in readout.signals] == ["infra"]
    assert readout.summaries == {}


@pytest.mark.parametrize(("path", "wanted"), [("x.y", 1), ("x", {"y": 1})])
def test_dig_walks_dotted_paths_and_names_nothing_missing(path: str, wanted: Any) -> None:
    assert _dig({"x": {"y": 1}}, path) == wanted
    assert _dig({"x": {}}, "x.y") is MISSING
    assert _dig(None, "x") is MISSING
    assert _dig({"x": 1}, "") == {"x": 1}
