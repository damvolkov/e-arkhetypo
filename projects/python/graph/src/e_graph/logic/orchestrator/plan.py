"""logic.orchestrator.plan: a section's catalog → the plan it runs by — steps in sequence, everything in a step at once.

Pure and deterministic. The specs a section schedules are every spec but those held as fallbacks (a
fallback runs only in its parent's place, in its parent's step). Their `depends` make a DAG — acyclic,
the rules proved it — whose topological generations are the steps: a spec lands in the first step after
all its dependencies, so every step holds only specs whose inputs earlier steps produced. Inside a step,
deterministic specs run each on its own; semantic specs are grouped by tier and packed into fused calls
within the fusion budget (instructions, examples, wiki, schema — the material each `pre_run` adds is
only known at run time, when a call may split again). Names are sorted wherever order is free: the same
catalog always yields the same plan."""

from itertools import groupby
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

import rustworkx as rx

from e_graph.logic.models import FusedCall, SectionPlan, SemanticSpec, Step, Tier
from e_graph.logic.orchestrator.fusion import SpecFusion

### tiers in their declared order: the higher model's calls are issued first within a step.
ORDER: Final[Mapping[Tier, int]] = MappingProxyType({tier: position for position, tier in enumerate(Tier)})

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from e_graph.logic.models import Catalog
    from infra.settings.darts import DartsSettings


class DagPlan:
    """Builds a section's plan from its catalog."""

    ##### PRIVATE #####

    @staticmethod
    def _build_generations(catalog: Catalog, scheduled: Sequence[str]) -> list[list[str]]:
        """The scheduled specs' topological generations, each sorted by name."""
        graph: rx.PyDiGraph[str, None] = rx.PyDiGraph()
        index = {name: graph.add_node(name) for name in scheduled}
        graph.add_edges_from_no_data(
            [
                (index[dependency], index[name])
                for name in scheduled
                for dependency in catalog.nodes[name].spec.depends
                if dependency in index
            ]
        )
        return [sorted(graph[node] for node in generation) for generation in rx.topological_generations(graph)]

    @staticmethod
    def _build_step(position: int, names: Sequence[str], catalog: Catalog, conf: DartsSettings) -> Step:
        """One generation as a step: deterministic specs alone, semantic ones fused by tier and packed by budget."""
        nodes = catalog.nodes
        tiers = {name: spec.tier for name in names if isinstance(spec := nodes[name].spec, SemanticSpec)}
        ordered = sorted(tiers, key=lambda name: (ORDER[tiers[name]], name))
        fused = [
            FusedCall(tier=tier, specs=specs)
            for tier, group in groupby(ordered, key=tiers.__getitem__)
            for specs in SpecFusion.pack(
                {name: SpecFusion.weight(nodes[name], catalog.wiki) for name in group},
                budget=conf.darts_fusion_tokens,
                most=conf.darts_fusion_specs,
            )
        ]
        return Step(
            index=position,
            deterministic=tuple(name for name in names if name not in tiers),
            fused=tuple(fused),
        )

    ############################################################

    ##### PUBLIC #####

    @classmethod
    def build(cls, catalog: Catalog, conf: DartsSettings) -> SectionPlan:
        """The section's plan: fallbacks held back for their parents, the rest in steps of topological generations."""
        fallbacks = {
            name: node.spec.fallback for name, node in sorted(catalog.nodes.items()) if node.spec.fallback is not None
        }
        held = set(fallbacks.values())
        scheduled = sorted(name for name in catalog.nodes if name not in held)
        generations = cls._build_generations(catalog, scheduled)
        return SectionPlan(
            pipeline=catalog.pipeline,
            section=catalog.section,
            steps=tuple(cls._build_step(position, names, catalog, conf) for position, names in enumerate(generations)),
            fallbacks=fallbacks,
        )
