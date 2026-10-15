"""pipelines.base: the builder every pipeline is, and the registry that finds them all — no import by hand.

A pipeline is a folder, `pipelines/<pipeline>/`: its wiring in `graph.py` — one `<Pipeline>Graph`, a
`PipelineBuilder` — and one node per section in `nodes/<section>/node.py`. `compose`, the builder's one
declarative space, chains `add_node` / `add_edge` / `add_conditional_edges` on the fresh graph it is
handed (every `add_*` returns the graph) and returns it. `build` owns everything else — the fresh graph
named after the folder, the compile, the built `InstrumentGraph` handed back — so a builder can never
return half a graph. The folder name is the pipeline's name: the path is the name.

`PipelineRegistry` sweeps the package with the core `FileFinder`: drop a new pipeline folder in
`pipelines/` and the next boot serves it, nothing else to touch. `build` returns the graphs by name —
singletons the system holds for every run to share."""

import asyncio
import importlib
import inspect
import re
from abc import ABC, abstractmethod
from collections import Counter
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from e_graph.instrument.graph import InstrumentGraph
from ops.file import FileFinder

if TYPE_CHECKING:
    from collections.abc import Mapping

    from e_graph.models.section import Section

PACKAGE: Final[str] = "e_graph.pipelines"
PATTERN: Final = re.compile(r"^[A-Z]\w*Graph$")
MODULE: Final[str] = "graph"


##### BUILDER #####
class PipelineBuilder(ABC):
    """One pipeline's declaration: `compose` says what the graph is, `build` makes it real, compiled."""

    __slots__ = ()

    @property
    def name(self) -> str:
        """The pipeline's name: the folder its graph lives in (`pipelines/doc/graph.py` → `doc`)."""
        return type(self).__module__.split(".")[-2]

    @property
    def summary(self) -> str:
        """What the pipeline is: the headline of the builder's docstring."""
        return (inspect.getdoc(type(self)) or "").partition("\n")[0]

    @property
    def seed(self) -> dict[str, Any]:
        """The run data the pipeline expects, ready-made: paths relative to the project root (where the
        server runs). A pipeline that needs none says so by not overriding."""
        return {}

    @abstractmethod
    def compose(self, graph: InstrumentGraph) -> InstrumentGraph:
        """Declare nodes and edges on the fresh graph and return it — `graph.add_node(...).add_edge(...)`."""

    def build(self) -> InstrumentGraph:
        """A fresh graph, named, summarized, seeded, composed by `compose`, compiled — built, never half-built."""
        graph = self.compose(InstrumentGraph(name=self.name, summary=self.summary, seed=self.seed))
        graph.compile()
        return graph


##### REGISTRY #####
class PipelineRegistry:
    """Every builder under the package, found by sweep; one per pipeline, or the sweep fails naming the clash."""

    __slots__ = ("_package",)

    def __init__(self, package: str = PACKAGE) -> None:
        self._package = package

    ##### PRIVATE #####

    def _discover_folders(self) -> list[str]:
        """The pipeline folders under the package: every one holding a `graph.py`, by name."""
        package = importlib.import_module(self._package)
        roots = (Path(root) for root in package.__path__)
        return sorted(entry.name for root in roots for entry in root.iterdir() if (entry / f"{MODULE}.py").is_file())

    ############################################################

    async def discover(self) -> Mapping[str, PipelineBuilder]:
        """Every concrete graph by pipeline name, in name order; the import walk runs off the loop."""
        sweeps = [FileFinder(f"{self._package}.{folder}") for folder in self._discover_folders()]
        found = await asyncio.gather(*(sweep.adiscover(PipelineBuilder, pattern=PATTERN) for sweep in sweeps))
        ### an abstract builder (a shared intermediate base) declares no pipeline: only concrete ones build.
        concrete = (
            declared()
            for declared in (cls for classes in found for cls in classes.values())
            if not inspect.isabstract(declared) and declared.__module__.rpartition(".")[2] == MODULE
        )
        builders = sorted(concrete, key=lambda builder: builder.name)
        match sorted(name for name, count in Counter(builder.name for builder in builders).items() if count > 1):
            case []:
                return MappingProxyType({builder.name: builder for builder in builders})
            case clashes:
                msg = f"one graph per pipeline under {self._package}: {clashes} declare several"
                raise ValueError(msg)

    async def build(self) -> Mapping[str, InstrumentGraph]:
        """Every pipeline built once, by name — the singletons a system holds."""
        return MappingProxyType({name: builder.build() for name, builder in (await self.discover()).items()})

    async def mounts(self) -> Mapping[str, frozenset[Section]]:
        """Every pipeline's mounted sections, by name — where its specs may run, what the static check holds them to."""
        return MappingProxyType({name: graph.sections for name, graph in (await self.build()).items()})
