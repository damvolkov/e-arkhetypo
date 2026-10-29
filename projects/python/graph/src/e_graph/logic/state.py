"""logic.state: the logic's typed branch, `system.logic` — one attribute per module of `logic/` the app holds alive.

`agent` is the agnostic agent (`logic.agent`), opened and closed by its lifespan; `orchestrator` is the DARTS engine
(`logic.orchestrator`), one for every pipeline. Every run reads them through `RunState.logic`."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from e_graph.logic.agent import AgnosticAgent
    from e_graph.logic.orchestrator.core import OrchestratorCore


@dataclass(frozen=True, slots=True)
class LogicState:
    """The logic's singletons: built once at startup, shared by every run, mutated by none."""

    agent: AgnosticAgent
    orchestrator: OrchestratorCore
