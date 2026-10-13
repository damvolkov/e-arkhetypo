"""api.deps: chained dependency providers — litestar resolves the graph recursively per request.

No FastAPI `Depends()` sugar: binding is by *name*. Each link declares what it consumes in its own
signature (`store` and `graphs` take `system`, `graph` takes `graphs` and the path's id), every route wires the chains it uses in a local
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

from adapters.ports import StorePort
from core.state import State
from e_graph.api.state import AppState
from e_graph.instrument.graph import InstrumentGraph


##### DEPENDENCY KEYS — the wiring vocabulary: a typo is an attribute error at import, never a silent runtime miss #####
class DepKey(StrEnum):
    SYSTEM = auto()
    STORE = auto()
    GRAPHS = auto()
    GRAPH = auto()
    CORRELATION_ID = auto()


##### LINKS — each names its injection parameter and consumes other links by name #####
def system(state: AppState) -> State:
    """Root of every chain: the app's sealed system graph, filled by the lifespans. HTTP and websocket alike."""
    return state.system


def store(system: NamedDependency[State]) -> StorePort:
    """The KV edge the app's records live on; swap scope here to send a route elsewhere. Chain: system."""
    return system.adapters.store


def graphs(system: NamedDependency[State]) -> Mapping[str, InstrumentGraph]:
    """Every built pipeline by name — the singletons the registry built at startup. Chain: system."""
    return system.graphs


def graph(pipeline_id: FromPath[str], graphs: NamedDependency[Mapping[str, InstrumentGraph]]) -> InstrumentGraph:
    """The built pipeline the path names, or 404 listing the names that exist. Chain: graphs + the path's id."""
    match graphs.get(pipeline_id):
        case None:
            raise NotFoundException(detail=f"no pipeline {pipeline_id!r}; known: {sorted(graphs)}")
        case found:
            return found


def correlation_id() -> str:
    """Request id propagated by `CorrelationIdMiddleware`; empty only when the middleware is off. Chain: none."""
    return correlation_id_var.get() or ""
