"""api.router.pipelines: every pipeline the app discovered, addressed by id — list, map, run batch, run live.

The canvas speaks these routes exactly as curl or any other client would:

    GET  /api/pipelines/list             the names and what each one is
    GET  /api/pipelines/topology/{id}    the declared graph as a placed map (nodes by rank and lane, arcs)
    POST /api/pipelines/batch/{id}       one run to completion: terminal outputs and the verdict
    WS   /api/pipelines/stream/{id}      one run live: send a RunRequest, receive every frame, then close

Every route reads the graph singletons the registry built at startup (`system.graphs`); both runs
build a fresh `RunState` over the app's sealed system — the run is the factory, the graph is shared —
and seed its `data` from the request.
A malformed stream request closes the socket with 1007 before anything runs; an unknown id is a 404."""

from collections.abc import Mapping
from typing import Final

import msgspec
from litestar import WebSocket, get, post, websocket
from litestar.di import NamedDependency, Provide
from litestar.handlers import HTTPRouteHandler, WebsocketRouteHandler
from litestar.status_codes import WS_1007_INVALID_FRAME_PAYLOAD_DATA

from core.state import State
from e_graph.api.deps import DepKey, correlation_id, graph, graphs, system
from e_graph.instrument.graph import InstrumentGraph
from e_graph.instrument.models import RunResult, Topology
from e_graph.instrument.state import RunState
from e_graph.models.pipeline import PipelineInfo
from e_graph.models.run import RunRequest

PREFIX: Final[str] = "/api/pipelines"
DECODER: Final = msgspec.json.Decoder(RunRequest)
ENCODER: Final = msgspec.json.Encoder()


async def listing(graphs: NamedDependency[Mapping[str, InstrumentGraph]]) -> tuple[PipelineInfo, ...]:
    """Every built pipeline, in name order."""
    return tuple(
        PipelineInfo(id=name, summary=graph.summary, nodes=len(graph.topology().nodes))
        for name, graph in graphs.items()
    )


async def topology(graph: NamedDependency[InstrumentGraph]) -> Topology:
    """The pipeline's declared graph as a placed map — O(V + E) over a graph that never changes."""
    return graph.topology()


async def batch(
    data: RunRequest,
    system: NamedDependency[State],
    graph: NamedDependency[InstrumentGraph],
    correlation_id: NamedDependency[str],
) -> RunResult:
    """Run to completion: every node's terminal output and the verdict. A failed run is a 200 with its verdict."""
    state = RunState(system, correlation=correlation_id)
    state.context.update(data.data)
    return await graph.run(state)


async def stream(
    socket: WebSocket,
    system: NamedDependency[State],
    graph: NamedDependency[InstrumentGraph],
    correlation_id: NamedDependency[str],
) -> None:
    """One request in, every run frame out as it happens, then close."""
    await socket.accept()
    try:
        request = DECODER.decode(await socket.receive_data(mode="text"))
    except msgspec.DecodeError as error:
        await socket.close(code=WS_1007_INVALID_FRAME_PAYLOAD_DATA, reason=str(error))
        return
    state = RunState(system, correlation=correlation_id)
    state.context.update(request.data)
    async for frame in graph.stream(state):
        await socket.send_data(ENCODER.encode(frame).decode(), mode="text")
    await socket.close()


##### CHAINS — endpoint-local wiring: enum-owned keys, .value only at the litestar edge #####
LIST_DEPS: Final[dict[str, Provide]] = {
    DepKey.SYSTEM.value: Provide(system, sync_to_thread=False),
    DepKey.GRAPHS.value: Provide(graphs, sync_to_thread=False),
}
GRAPH_DEPS: Final[dict[str, Provide]] = {
    **LIST_DEPS,
    DepKey.GRAPH.value: Provide(graph, sync_to_thread=False),
    DepKey.CORRELATION_ID.value: Provide(correlation_id, sync_to_thread=False),
}

ROUTES: tuple[HTTPRouteHandler | WebsocketRouteHandler, ...] = (
    get("/list", name="pipelines.list", dependencies=LIST_DEPS)(listing),
    get("/topology/{pipeline_id:str}", name="pipelines.topology", dependencies=GRAPH_DEPS)(topology),
    post("/batch/{pipeline_id:str}", name="pipelines.batch", status_code=200, dependencies=GRAPH_DEPS)(batch),
    websocket("/stream/{pipeline_id:str}", name="pipelines.stream", dependencies=GRAPH_DEPS)(stream),
)
