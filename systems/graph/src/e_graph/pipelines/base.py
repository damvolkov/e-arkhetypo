"""pipelines.base: the builder every pipeline is, and the registry that finds them all — no import by hand.

A pipeline is a `PipelineBuilder` in its own module under `pipelines/`: one declarative space,
`compose`, chains `add_node` / `add_edge` / `add_conditional_edges` on the fresh graph it is handed
(every `add_*` returns the graph) and returns it. `build` owns everything else — the fresh graph named
after the module, the compile, the built `InstrumentGraph` handed back — so a builder can never return
half a graph. The module name is the pipeline's name: the path is the name, one builder per module.

`PipelineRegistry` sweeps the package with the core `FileFinder`: drop a new builder module in
`pipelines/` and the next boot serves it, nothing else to touch. `build` returns the graphs by name —
singletons the system holds for every run to share."""

import inspect
import re
from abc import ABC, abstractmethod
from collections import Counter
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from e_graph.instrument.graph import InstrumentGraph
from ops.file import FileFinder

if TYPE_CHECKING:
    from collections.abc import Mapping

PACKAGE: Final[str] = "e_graph.pipelines"
PATTERN: Final = re.compile(r"^[A-Z]\w*Builder$")


##### BUILDER #####
class PipelineBuilder(ABC):
    """One pipeline's declaration: `compose` says what the graph is, `build` makes it real, compiled."""

    __slots__ = ()

    @property
    def name(self) -> str:
        """The pipeline's name: the module it lives in (`pipelines/doc.py` → `doc`)."""
        return type(self).__module__.rpartition(".")[2]

    @property
    def summary(self) -> str:
        """What the pipeline is: the headline of the builder's docstring."""
        return (inspect.getdoc(type(self)) or "").partition("\n")[0]

    @abstractmethod
    def compose(self, graph: InstrumentGraph) -> InstrumentGraph:
        """Declare nodes and edges on the fresh graph and return it — `graph.add_node(...).add_edge(...)`."""

    def build(self) -> InstrumentGraph:
        """A fresh graph, named and summarized, composed by `compose`, compiled — built, never half-built."""
        graph = self.compose(InstrumentGraph(name=self.name, summary=self.summary))
        graph.compile()
        return graph


##### REGISTRY #####
class PipelineRegistry:
    """Every builder under the package, found by sweep; one per module, or the sweep fails naming the clash."""

    __slots__ = ("_package",)

    def __init__(self, package: str = PACKAGE) -> None:
        self._package = package

    async def discover(self) -> Mapping[str, PipelineBuilder]:
        """Every concrete builder by name, in name order; the import walk runs off the loop."""
        found = await FileFinder(self._package).adiscover(PipelineBuilder, pattern=PATTERN)
        ### an abstract builder (a shared intermediate base) declares no pipeline: only concrete ones build.
        concrete = (declared() for declared in found.values() if not inspect.isabstract(declared))
        builders = sorted(concrete, key=lambda builder: builder.name)
        match sorted(name for name, count in Counter(builder.name for builder in builders).items() if count > 1):
            case []:
                return MappingProxyType({builder.name: builder for builder in builders})
            case clashes:
                msg = f"one builder per module under {self._package}: {clashes} declare several"
                raise ValueError(msg)

    async def build(self) -> Mapping[str, InstrumentGraph]:
        """Every pipeline built once, by name — the singletons a system holds."""
        return MappingProxyType({name: builder.build() for name, builder in (await self.discover()).items()})
