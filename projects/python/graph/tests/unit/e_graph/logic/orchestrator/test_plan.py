"""tests/unit: logic.orchestrator.plan — the diagram's plan exactly as drawn, then the laws on random crafted DAGs."""

from typing import TYPE_CHECKING

from core.settings.darts import DartsSettings
from e_graph.logic.models import FusedCall, SemanticSpec, Step, Tier
from e_graph.logic.orchestrator.plan import DagPlan
from support.darts import SECTION

if TYPE_CHECKING:
    from support.crafter import SpecCrafter
    from support.darts import DartsHarness


async def test_the_diagram_plans_as_drawn(darts: DartsHarness) -> None:
    darts.diagram()
    plan = await darts.orchestrator.plan("doc", SECTION)
    assert plan.steps == (
        Step(
            index=0,
            deterministic=("EXT-lines", "EXT-meta"),
            fused=(FusedCall(tier=Tier.MEDIUM, specs=("EXT-kind", "EXT-party")),),
        ),
        Step(index=1, fused=(FusedCall(tier=Tier.MEDIUM, specs=("EXT-currency", "EXT-total")),)),
        Step(index=2, deterministic=("EXT-audit",)),
    )
    assert plan.fallbacks == {"EXT-audit": "EXT-recount"}
    assert plan.steps[0].specs == ("EXT-lines", "EXT-meta", "EXT-kind", "EXT-party")


async def test_tiers_never_share_a_call_and_higher_tiers_come_first(darts: DartsHarness) -> None:
    darts.semantic("EXT-a", tier="low")
    darts.semantic("EXT-b", tier="high")
    darts.semantic("EXT-c", tier="high")
    (step,) = (await darts.orchestrator.plan("doc", SECTION)).steps
    assert step.fused == (
        FusedCall(tier=Tier.HIGH, specs=("EXT-b", "EXT-c")),
        FusedCall(tier=Tier.LOW, specs=("EXT-a",)),
    )


async def test_a_group_over_budget_splits_into_calls(darts: DartsHarness) -> None:
    for name in ("EXT-a", "EXT-b", "EXT-c"):
        darts.semantic(name, instructions="Read the totals carefully. " * 40)
    darts.configure(darts_fusion_tokens=400)
    (step,) = (await darts.orchestrator.plan("doc", SECTION)).steps
    assert [call.specs for call in step.fused] == [("EXT-a",), ("EXT-b",), ("EXT-c",)]
    darts.configure(darts_fusion_specs=2)
    (step,) = (await darts.orchestrator.plan("doc", SECTION)).steps
    assert [len(call.specs) for call in step.fused] == [2, 1]


async def test_random_dags_plan_by_their_laws(crafter: SpecCrafter) -> None:
    blueprint = crafter.craft(SECTION, n=14, semantic=0.5, fallbacks=2, density=0.35)
    catalog = await crafter.discover().catalog(SECTION)
    plan = DagPlan.build(catalog, DartsSettings())
    position = {name: step.index for step in plan.steps for name in step.specs}
    held = set(blueprint.fallbacks.values())
    ### every scheduled spec exactly once; fallbacks never scheduled, held for their parents.
    assert sorted(position) == sorted(set(blueprint.specs) - held)
    assert sum(len(step.specs) for step in plan.steps) == len(position)
    assert plan.fallbacks == blueprint.fallbacks
    ### a spec runs strictly after everything it depends on — and as early as that allows.
    assert all(position[dependency] < position[name] for dependency, name in blueprint.edges)
    assert all(
        position[name] == max((position[dependency] + 1 for dependency in blueprint.specs[name].depends), default=0)
        for name in position
    )
    ### the kinds land where they belong: semantic specs only in fused calls, deterministic ones only alone.
    fused = {name for step in plan.steps for call in step.fused for name in call.specs}
    assert fused == {name for name in position if isinstance(blueprint.specs[name], SemanticSpec)}
    assert plan == DagPlan.build(catalog, DartsSettings())
