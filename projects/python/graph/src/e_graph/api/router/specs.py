"""api.router.specs: the orchestrator's sections, addressed by pipeline and section — the spec-node level.

The same shape as the pipeline level, one level down — a pipeline's node opened into the specs it runs:

    GET  /api/specs/list                          every mounted section: specs, steps, planned agent calls
    GET  /api/specs/topology/{id}/{section}       the section placed for drawing: specs by step and lane, arcs, calls
    GET  /api/specs/svg/{id}/{section}            the same section drawn by Graphviz (WebAssembly), as SVG
    POST /api/specs/simulate/{id}/{section}       the pipeline rehearsed up to the section: runs, agent calls whole

An unknown pipeline or a section it does not mount is a 404; a section whose specs break a DARTS law is a
422 naming every breach."""

from typing import Final

from litestar import Response, get, post
from litestar.di import NamedDependency, Provide
from litestar.exceptions import HTTPException
from litestar.handlers import HTTPRouteHandler
from litestar.status_codes import HTTP_422_UNPROCESSABLE_ENTITY

from e_graph.api.deps import DepKey, graph, graphs, lab, section, system
from e_graph.instrument.graph import InstrumentGraph
from e_graph.logic.errors import CatalogError
from e_graph.logic.models import SectionInfo, SectionMap, Simulation
from e_graph.logic.orchestrator.lab import SectionLab
from e_graph.models.run import SimulateRequest
from e_graph.models.section import Section
from infra.state import State

PREFIX: Final[str] = "/api/specs"
SVG: Final[str] = "image/svg+xml"


def broken(error: CatalogError) -> HTTPException:
    """A section that breaks its laws, as the 422 that names every breach."""
    breaches = [f"[{breach.rule}] {breach.subject}: {breach.detail}" for breach in error.breaches]
    return HTTPException(status_code=HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error), extra={"breaches": breaches})


async def listing(lab: NamedDependency[SectionLab]) -> tuple[SectionInfo, ...]:
    """Every mounted section of every pipeline, in walking order."""
    return await lab.sections()


async def topology(
    graph: NamedDependency[InstrumentGraph], section: NamedDependency[Section], lab: NamedDependency[SectionLab]
) -> SectionMap:
    """The section as the orchestrator will run it, placed for drawing."""
    try:
        return await lab.map(graph.name, section)
    except CatalogError as error:
        raise broken(error) from error


async def svg(
    graph: NamedDependency[InstrumentGraph], section: NamedDependency[Section], lab: NamedDependency[SectionLab]
) -> Response[str]:
    """The section drawn: rustworkx's DOT rendered by Graphviz on wasmtime."""
    mapped = await topology(graph, section, lab)
    return Response(await lab.render(lab.dot(mapped)), media_type=SVG)


async def simulate(
    data: SimulateRequest,
    system: NamedDependency[State],
    graph: NamedDependency[InstrumentGraph],
    section: NamedDependency[Section],
    lab: NamedDependency[SectionLab],
) -> Simulation:
    """The pipeline rehearsed up to the section: every section's run and the section's agent calls, whole."""
    try:
        return await lab.simulate(graph.name, section, data.data, system=system, live=data.live)
    except CatalogError as error:
        raise broken(error) from error


##### CHAINS #####
LIST_DEPS: Final[dict[str, Provide]] = {
    DepKey.SYSTEM.value: Provide(system, sync_to_thread=False),
    DepKey.LAB.value: Provide(lab, sync_to_thread=False),
}
SECTION_DEPS: Final[dict[str, Provide]] = {
    **LIST_DEPS,
    DepKey.GRAPHS.value: Provide(graphs, sync_to_thread=False),
    DepKey.GRAPH.value: Provide(graph, sync_to_thread=False),
    DepKey.SECTION.value: Provide(section, sync_to_thread=False),
}

ROUTES: tuple[HTTPRouteHandler, ...] = (
    get("/list", name="specs.list", dependencies=LIST_DEPS)(listing),
    get("/topology/{pipeline_id:str}/{section_id:str}", name="specs.topology", dependencies=SECTION_DEPS)(topology),
    get("/svg/{pipeline_id:str}/{section_id:str}", name="specs.svg", dependencies=SECTION_DEPS)(svg),
    post(
        "/simulate/{pipeline_id:str}/{section_id:str}",
        name="specs.simulate",
        status_code=200,
        dependencies=SECTION_DEPS,
    )(simulate),
)
