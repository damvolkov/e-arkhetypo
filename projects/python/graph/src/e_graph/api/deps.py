"""api.deps: chained dependency providers — litestar resolves the graph recursively per request.

No FastAPI `Depends()` sugar: binding is by *name*. Each link declares what it consumes in its own
signature (`store` and `graphs` take `system`, `graph` takes `graphs` and the path's id, `section` takes `graph`
and the path's section, `lab` takes `system`), every route wires the chains it uses in a local
`dependencies` mapping, and the app itself registers nothing. Links run once per request, in
resolved order. The root is `system` — the same name the RunState gives it — read off Litestar's
reserved `state` kwarg, annotated `AppState` so Litestar builds the typed class itself, on HTTP and
websocket connections alike.
"""

from collections.abc import Mapping
from enum import StrEnum, auto

from asgi_correlation_id import correlation_id as correlation_id_var
from litestar.di import NamedDependency
from litestar.exceptions import NotFoundException
from litestar.params import FromPath

from e_graph.api.state import AppState
from e_graph.instrument.graph import InstrumentGraph
from e_graph.logic.orchestrator.lab import SectionLab
from e_graph.models.section import Section
from infra.state import State
from ports.store import StorePort


##### DEPENDENCY KEYS — the wiring vocabulary: a typo is an attribute error at import, never a silent runtime miss #####
class DepKey(StrEnum):
    SYSTEM = auto()
    STORE = auto()
    GRAPHS = auto()
    GRAPH = auto()
    SECTION = auto()
    LAB = auto()
    CORRELATION_ID = auto()


##### LINKS — each names its injection parameter and consumes other links by name #####
def system(state: AppState) -> State:
    """Root of every chain: the app's sealed system graph, filled by the lifespans. HTTP and websocket alike."""
    return state.system


def store(system: NamedDependency[State]) -> StorePort:
    """The KV provider the app's records live on; swap scope here to send a route elsewhere. Chain: system."""
    return system.infra.providers.store


def graphs(system: NamedDependency[State]) -> Mapping[str, InstrumentGraph]:
    """Every built pipeline by name — the singletons the registry built at startup. Chain: system."""
    return system.infra.graphs


def graph(pipeline_id: FromPath[str], graphs: NamedDependency[Mapping[str, InstrumentGraph]]) -> InstrumentGraph:
    """The built pipeline the path names, or 404 listing the names that exist. Chain: graphs + the path's id."""
    match graphs.get(pipeline_id):
        case None:
            raise NotFoundException(detail=f"no pipeline {pipeline_id!r}; known: {sorted(graphs)}")
        case found:
            return found


def section(section_id: FromPath[str], graph: NamedDependency[InstrumentGraph]) -> Section:
    """The section the path names, mounted by the path's pipeline, or 404 listing those it mounts. Chain: graph."""
    mounted = {str(found): found for found in graph.sections}
    match mounted.get(section_id):
        case None:
            raise NotFoundException(detail=f"{graph.name} mounts no {section_id!r}; mounted: {sorted(mounted)}")
        case found:
            return found


def lab(system: NamedDependency[State]) -> SectionLab:
    """The orchestrator's sections seen from outside, over the app's own orchestrator and graphs. Chain: system."""
    return SectionLab(system.logic.orchestrator, system.infra.graphs)


def correlation_id() -> str:
    """Request id propagated by `CorrelationIdMiddleware`; empty only when the middleware is off. Chain: none."""
    return correlation_id_var.get() or ""
